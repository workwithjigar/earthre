"""SLA statistics computed from stored check records.

Everything works on "slots": one service x one 15-minute check window.
A slot can have several readings (one per agent). It is:
  * down    - if any valid reading failed (4xx/5xx)
  * up      - if it has valid readings and none failed
  * unknown - if its only readings have an invalid status code
Availability = up / (up + down). Unknown and missing slots are excluded.
"""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Mapping

SLOT = timedelta(minutes=15)
SLOT_MINUTES = 15


@dataclass
class Slot:
    service_id: str
    ts: datetime
    outcome: str  # up | down | unknown
    latency_ms: float | None
    status_codes: list[int] = field(default_factory=list)


@dataclass
class StatsConfig:
    sla_target: float = 99.9  # percent
    slow_ms: float = 1000.0
    incident_max_gap: int = 2  # healthy slots allowed inside one incident
    incident_min_bad: int = 3  # one or two scattered errors are blips, not an incident
    # (availability below which the credit applies, credit % of monthly bill)
    credit_tiers: tuple[tuple[float, int], ...] = ((99.9, 10), (99.0, 25), (95.0, 100))


def build_slots(rows: Iterable[Mapping]) -> dict[str, list[Slot]]:
    grouped: dict[tuple[str, datetime], list[Mapping]] = defaultdict(list)
    for r in rows:
        grouped[(r["service_id"], r["ts"])].append(r)

    by_service: dict[str, list[Slot]] = defaultdict(list)
    for (sid, ts), readings in grouped.items():
        outcomes = {r["outcome"] for r in readings}
        if "down" in outcomes:
            outcome = "down"
        elif "up" in outcomes:
            outcome = "up"
        else:
            outcome = "unknown"
        latencies = [r["latency_ms"] for r in readings if r["latency_ms"] is not None]
        by_service[sid].append(
            Slot(
                service_id=sid,
                ts=ts,
                outcome=outcome,
                latency_ms=sum(latencies) / len(latencies) if latencies else None,
                status_codes=[r["status_code"] for r in readings if r["status_code"] is not None],
            )
        )
    for slots in by_service.values():
        slots.sort(key=lambda s: s.ts)
    return dict(by_service)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def availability(up: int, down: int) -> float | None:
    total = up + down
    return round(100 * up / total, 4) if total else None


def credit_for(avail: float | None, cfg: StatsConfig) -> int:
    if avail is None:
        return 0
    credit = 0
    for threshold, pct in cfg.credit_tiers:
        if avail < threshold:
            credit = pct
    return credit


def detect_incidents(slots: list[Slot], cfg: StatsConfig) -> list[dict]:
    """Group bad slots (down, or slower than slow_ms) into incident windows."""

    def is_bad(s: Slot) -> bool:
        return s.outcome == "down" or (s.latency_ms is not None and s.latency_ms > cfg.slow_ms)

    windows: list[list[Slot]] = []
    last_bad: datetime | None = None
    for s in slots:
        if not is_bad(s):
            continue
        gap = int((s.ts - last_bad) / SLOT) - 1 if last_bad else None
        if gap is not None and gap <= cfg.incident_max_gap:
            windows[-1].append(s)
        else:
            windows.append([s])
        last_bad = s.ts

    incidents = []
    for w in windows:
        if len(w) < cfg.incident_min_bad:
            continue
        start, end = w[0].ts, w[-1].ts + SLOT
        codes: Counter[int] = Counter(c for s in w for c in s.status_codes if 400 <= c <= 599)
        latencies = [s.latency_ms for s in w if s.latency_ms is not None]
        incidents.append(
            {
                "service_id": w[0].service_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "duration_minutes": int((end - start).total_seconds() // 60),
                "failed_checks": sum(1 for s in w if s.outcome == "down"),
                "slow_checks": sum(1 for s in w if s.outcome != "down" and is_bad(s)),
                "peak_latency_ms": max(latencies) if latencies else None,
                "status_codes": {str(k): v for k, v in sorted(codes.items())},
            }
        )
    return incidents


def _summarise(slots: list[Slot], cfg: StatsConfig) -> dict:
    counts = Counter(s.outcome for s in slots)
    up, down, unknown = counts["up"], counts["down"], counts["unknown"]
    avail = availability(up, down)
    allowed_down = (1 - cfg.sla_target / 100) * (up + down)
    latencies = [s.latency_ms for s in slots if s.latency_ms is not None]
    return {
        "checks": len(slots),
        "up": up,
        "down": down,
        "unknown": unknown,
        "availability": avail,
        "sla_met": avail is None or avail >= cfg.sla_target,
        "downtime_minutes": down * SLOT_MINUTES,
        "allowed_downtime_minutes": round(allowed_down * SLOT_MINUTES, 1),
        "error_budget_used_pct": round(100 * down / allowed_down, 1) if allowed_down else None,
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "latency_p99_ms": percentile(latencies, 99),
        "slow_checks": sum(1 for v in latencies if v > cfg.slow_ms),
    }


def compute_stats(rows: Iterable[Mapping], names: Mapping[str, str], cfg: StatsConfig) -> dict:
    by_service = build_slots(rows)

    services = []
    all_incidents = []
    daily = []
    for sid in sorted(by_service):
        slots = by_service[sid]
        summary = _summarise(slots, cfg)
        incidents = detect_incidents(slots, cfg)
        all_incidents.extend(incidents)
        services.append({"service_id": sid, "service_name": names.get(sid, sid), **summary, "incidents": len(incidents)})

        per_day: dict[str, Counter[str]] = defaultdict(Counter)
        for s in slots:
            per_day[s.ts.date().isoformat()][s.outcome] += 1
        for day, c in sorted(per_day.items()):
            daily.append(
                {
                    "service_id": sid,
                    "date": day,
                    "availability": availability(c["up"], c["down"]),
                    "down": c["down"],
                }
            )

    all_slots = [s for slots in by_service.values() for s in slots]
    fleet = _summarise(all_slots, cfg) if all_slots else None
    all_incidents.sort(key=lambda i: i["start"])
    worst = min((s for s in services if s["availability"] is not None), key=lambda s: s["availability"], default=None)

    return {
        "config": {"sla_target": cfg.sla_target, "slow_ms": cfg.slow_ms, "credit_tiers": cfg.credit_tiers},
        "overview": {
            "services": len(services),
            "services_breaching": sum(1 for s in services if not s["sla_met"]),
            "fleet_availability": fleet["availability"] if fleet else None,
            "total_downtime_minutes": fleet["downtime_minutes"] if fleet else 0,
            "incidents": len(all_incidents),
            "worst_service": worst["service_id"] if worst else None,
            "worst_availability": worst["availability"] if worst else None,
            "unknown_checks": fleet["unknown"] if fleet else 0,
            "slow_checks": fleet["slow_checks"] if fleet else 0,
        },
        "services": services,
        "incidents": all_incidents,
        "daily": daily,
    }


def compute_monthly(rows: Iterable[Mapping], names: Mapping[str, str], cfg: StatsConfig) -> list[dict]:
    """SLAs are defined per calendar month, so billing credits are only computed here."""
    by_service = build_slots(rows)
    out = []
    for sid in sorted(by_service):
        per_month: dict[str, list[Slot]] = defaultdict(list)
        for s in by_service[sid]:
            per_month[s.ts.strftime("%Y-%m")].append(s)
        for month, slots in sorted(per_month.items()):
            year, mon = map(int, month.split("-"))
            days_in_month = calendar.monthrange(year, mon)[1]
            days_observed = len({s.ts.date() for s in slots})
            summary = _summarise(slots, cfg)
            out.append(
                {
                    "service_id": sid,
                    "service_name": names.get(sid, sid),
                    "month": month,
                    "days_observed": days_observed,
                    "days_in_month": days_in_month,
                    "partial": days_observed < days_in_month,
                    "availability": summary["availability"],
                    "sla_met": summary["sla_met"],
                    "downtime_minutes": summary["downtime_minutes"],
                    "credit_pct": credit_for(summary["availability"], cfg),
                }
            )
    return out
