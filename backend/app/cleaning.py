"""Parse, validate and clean a raw monitoring-check CSV.

Pure functions only: bytes in, clean records + a data-quality report out.
No database or HTTP here, so the whole pipeline is unit-testable.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

SLOT = timedelta(minutes=15)
EPOCH = datetime(1970, 1, 1)

REQUIRED_COLUMNS = ("service_id", "timestamp", "status_code")
OPTIONAL_COLUMNS = ("service_name", "latency", "latency_unit", "agent", "region")

SECONDS_UNITS = {"s", "sec", "secs", "second", "seconds"}
MILLIS_UNITS = {"ms", "msec", "msecs", "millisecond", "milliseconds"}

# code -> (human description, what the pipeline does about it)
ISSUES: dict[str, tuple[str, str]] = {
    "blank_row": ("Blank line", "Skipped"),
    "repeated_header": ("Header row repeated inside the file", "Skipped"),
    "malformed_row": ("Row has the wrong number of columns", "Rejected"),
    "missing_service_id": ("Row has no service_id", "Rejected"),
    "bad_timestamp": ("Timestamp could not be parsed", "Rejected"),
    "exact_duplicate": ("Exact duplicate of another row", "Dropped, one copy kept"),
    "same_agent_duplicate": (
        "Same agent reported the same service + 15-min slot more than once "
        "(typically the same reading written once as epoch and once as ISO)",
        "Merged into one record, preferring the copy with a valid status and a latency",
    ),
    "conflicting_duplicate": (
        "Same agent, same slot, but the copies disagree on up/down",
        "Kept the failing copy (customer-favourable)",
    ),
    "epoch_timestamp": ("Timestamp given as Unix epoch seconds", "Converted to UTC"),
    "offset_timestamp": (
        "Timestamp carries a non-UTC offset (e.g. +05:30, the agent's local IST time)",
        "Converted to UTC",
    ),
    "naive_timestamp": ("Timestamp has no timezone", "Assumed UTC"),
    "off_grid_timestamp": ("Timestamp not on the 15-minute grid", "Snapped to nearest slot"),
    "seconds_latency": ("Latency reported in seconds instead of ms", "Multiplied by 1000"),
    "missing_latency_unit": ("Latency unit blank", "Assumed ms"),
    "unknown_latency_unit": ("Latency unit not recognised", "Latency nulled; status still counts"),
    "missing_latency": ("Latency blank", "Stored as null; status still counts for availability"),
    "invalid_latency": ("Latency is not a number", "Latency nulled; status still counts"),
    "negative_latency": ("Negative latency (physically impossible)", "Latency nulled; status still counts"),
    "invalid_status": (
        "Status code outside the HTTP range 100-599 (e.g. 999)",
        "Kept in logs as INVALID, excluded from availability",
    ),
    "service_name_mismatch": (
        "service_name disagrees with the name used by most rows for that service_id",
        "Normalised to the majority name",
    ),
}


class CsvValidationError(ValueError):
    """The file is unusable as a whole (wrong columns, not CSV, empty...)."""


@dataclass
class CleanRecord:
    service_id: str
    service_name: str
    ts: datetime  # naive UTC, aligned to the 15-minute grid
    raw_timestamp: str
    status_code: int | None
    latency_ms: float | None
    outcome: str  # "up" | "down" | "invalid"
    agent: str
    region: str
    flags: list[str] = field(default_factory=list)


@dataclass
class CleanResult:
    records: list[CleanRecord]
    report: dict


# --------------------------------------------------------------------------- #
# Field parsers
# --------------------------------------------------------------------------- #


def parse_timestamp(raw: str) -> tuple[datetime, list[str]]:
    """Return a naive-UTC datetime plus flags describing what was normalised."""
    s = raw.strip()
    if re.fullmatch(r"\d{9,10}", s):
        return EPOCH + timedelta(seconds=int(s)), ["epoch_timestamp"]
    if re.fullmatch(r"\d{12,13}", s):
        return EPOCH + timedelta(milliseconds=int(s)), ["epoch_timestamp"]

    # Python 3.10's fromisoformat does not accept a trailing "Z".
    dt = datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", s))
    if dt.tzinfo is None:
        return dt, ["naive_timestamp"]
    flags = ["offset_timestamp"] if dt.utcoffset() != timedelta(0) else []
    return dt.astimezone(timezone.utc).replace(tzinfo=None), flags


def snap_to_slot(dt: datetime) -> tuple[datetime, bool]:
    """Round to the nearest 15-minute slot. Returns (slot, was_off_grid)."""
    step = SLOT.total_seconds()
    secs = (dt - EPOCH).total_seconds()
    slot = EPOCH + timedelta(seconds=round(secs / step) * step)
    return slot, slot != dt


def parse_latency(raw: str, unit: str) -> tuple[float | None, list[str]]:
    raw, unit = raw.strip(), unit.strip().lower()
    if raw == "":
        return None, ["missing_latency"]
    try:
        value = float(raw)
    except ValueError:
        return None, ["invalid_latency"]

    flags: list[str] = []
    if unit in SECONDS_UNITS:
        value *= 1000
        flags.append("seconds_latency")
    elif unit == "":
        flags.append("missing_latency_unit")
    elif unit not in MILLIS_UNITS:
        return None, ["unknown_latency_unit"]

    if value < 0:
        return None, flags + ["negative_latency"]
    return round(value, 3), flags


def parse_status(raw: str) -> tuple[int | None, list[str]]:
    try:
        code = int(float(raw.strip()))
    except ValueError:
        return None, ["invalid_status"]
    if not 100 <= code <= 599:
        return code, ["invalid_status"]  # keep the raw value visible in the logs
    return code, []


def outcome_for(status: int | None, flags: list[str]) -> str:
    if status is None or "invalid_status" in flags:
        return "invalid"
    # 1xx-3xx: the endpoint answered. 4xx/5xx: the health check failed.
    return "up" if status < 400 else "down"


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


class _IssueTracker:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = defaultdict(list)

    def add(self, code: str, example: str | None = None, n: int = 1) -> None:
        self.counts[code] += n
        if example is not None and len(self.examples[code]) < 3:
            self.examples[code].append(example)

    def as_list(self) -> list[dict]:
        out = []
        for code, count in self.counts.most_common():
            label, action = ISSUES.get(code, (code, ""))
            out.append(
                {"code": code, "label": label, "action": action, "count": count, "examples": self.examples[code]}
            )
        return out


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _merge_same_agent(group: list[CleanRecord]) -> tuple[CleanRecord, bool]:
    """Pick one record out of several copies from the same agent for one slot."""
    valid_outcomes = {r.outcome for r in group if r.outcome != "invalid"}
    conflicting = len(valid_outcomes) > 1

    def rank(r: CleanRecord) -> tuple:
        return (
            r.outcome != "invalid",  # a usable status beats an invalid one
            r.outcome == "down" if conflicting else True,  # on conflict, keep the failure
            r.latency_ms is not None,  # having a latency beats not having one
            -len(r.flags),  # the least-normalised copy is the most trustworthy
        )

    best = max(group, key=rank)
    return best, conflicting


def clean_csv(data: bytes) -> CleanResult:
    if not data.strip():
        raise CsvValidationError("The file is empty.")

    text = _decode(data)
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise CsvValidationError("Could not read a CSV header row.") from exc

    columns = [h.strip().lower() for h in header]
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise CsvValidationError(
            f"Missing required column(s): {', '.join(missing)}. Found: {', '.join(columns) or 'none'}."
        )
    idx = {c: columns.index(c) for c in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if c in columns}

    issues = _IssueTracker()
    rows_received = 0
    seen_raw: set[tuple[str, ...]] = set()
    parsed: list[CleanRecord] = []
    out_of_order = 0
    prev_ts: datetime | None = None

    for line_no, row in enumerate(reader, start=2):
        rows_received += 1
        stripped = tuple(v.strip() for v in row)
        preview = ",".join(row)[:160]

        if not any(stripped):
            issues.add("blank_row", f"line {line_no}")
            continue
        if [v.lower() for v in stripped] == columns:
            issues.add("repeated_header", f"line {line_no}")
            continue
        if len(row) != len(columns):
            issues.add("malformed_row", f"line {line_no}: {preview}")
            continue
        if stripped in seen_raw:
            issues.add("exact_duplicate", f"line {line_no}: {preview}")
            continue
        seen_raw.add(stripped)

        def get(col: str) -> str:
            return stripped[idx[col]] if col in idx else ""

        service_id = get("service_id")
        if not service_id:
            issues.add("missing_service_id", f"line {line_no}: {preview}")
            continue

        raw_ts = get("timestamp")
        try:
            ts, flags = parse_timestamp(raw_ts)
        except ValueError:
            issues.add("bad_timestamp", f"line {line_no}: {raw_ts!r}")
            continue

        slot, off_grid = snap_to_slot(ts)
        if off_grid:
            flags.append("off_grid_timestamp")

        status, status_flags = parse_status(get("status_code"))
        latency, latency_flags = parse_latency(get("latency"), get("latency_unit"))
        flags += status_flags + latency_flags
        for f in flags:
            issues.add(f, f"line {line_no}: {preview}")

        if prev_ts is not None and slot < prev_ts:
            out_of_order += 1
        prev_ts = slot

        parsed.append(
            CleanRecord(
                service_id=service_id,
                service_name=get("service_name"),
                ts=slot,
                raw_timestamp=raw_ts,
                status_code=status,
                latency_ms=latency,
                outcome=outcome_for(status, status_flags),
                agent=get("agent") or "unknown",
                region=get("region") or "unknown",
                flags=flags,
            )
        )

    if not parsed:
        raise CsvValidationError("No usable rows were found in the file.")

    # service_name consistency: majority name per service_id wins.
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for r in parsed:
        if r.service_name:
            names[r.service_id][r.service_name] += 1
    canonical = {sid: c.most_common(1)[0][0] for sid, c in names.items()}
    for r in parsed:
        name = canonical.get(r.service_id, r.service_id)
        if r.service_name != name:
            issues.add("service_name_mismatch", f"{r.service_id}: {r.service_name!r} -> {name!r}")
            r.flags.append("service_name_mismatch")
            r.service_name = name

    # Same agent + same service + same slot = one observation reported twice.
    by_key: dict[tuple[str, datetime, str], list[CleanRecord]] = defaultdict(list)
    for r in parsed:
        by_key[(r.service_id, r.ts, r.agent)].append(r)

    records: list[CleanRecord] = []
    for (sid, ts, agent), group in by_key.items():
        if len(group) == 1:
            records.append(group[0])
            continue
        best, conflicting = _merge_same_agent(group)
        example = f"{sid} {ts:%Y-%m-%d %H:%M} {agent}: " + " | ".join(r.raw_timestamp for r in group)
        issues.add("same_agent_duplicate", example, n=len(group) - 1)
        best.flags.append("same_agent_duplicate")
        if conflicting:
            issues.add("conflicting_duplicate", example)
            best.flags.append("conflicting_duplicate")
        records.append(best)

    records.sort(key=lambda r: (r.ts, r.service_id, r.agent))
    report = _build_report(records, issues, rows_received, out_of_order)
    return CleanResult(records=records, report=report)


def _build_report(records: list[CleanRecord], issues: _IssueTracker, rows_received: int, out_of_order: int) -> dict:
    start, end = records[0].ts, records[-1].ts
    expected_slots = int((end - start) / SLOT) + 1

    # Coverage: which 15-minute slots have no reading at all for a service.
    per_service_slots: dict[str, set[datetime]] = defaultdict(set)
    per_slot_outcomes: dict[tuple[str, datetime], set[str]] = defaultdict(set)
    per_slot_agents: dict[tuple[str, datetime], set[str]] = defaultdict(set)
    for r in records:
        per_service_slots[r.service_id].add(r.ts)
        per_slot_agents[(r.service_id, r.ts)].add(r.agent)
        if r.outcome != "invalid":
            per_slot_outcomes[(r.service_id, r.ts)].add(r.outcome)

    coverage = {}
    for sid, slots in sorted(per_service_slots.items()):
        missing = expected_slots - len(slots)
        coverage[sid] = {"expected_slots": expected_slots, "present_slots": len(slots), "missing_slots": missing}

    multi_agent_slots = sum(1 for a in per_slot_agents.values() if len(a) > 1)
    disagreements = sum(1 for o in per_slot_outcomes.values() if len(o) > 1)
    invalid_only_slots = sum(1 for key in per_slot_agents if not per_slot_outcomes.get(key))

    observations = []
    if out_of_order:
        observations.append(
            f"Rows are not in chronological order ({out_of_order} backwards steps); records are sorted on ingest."
        )
    if multi_agent_slots:
        observations.append(
            f"{multi_agent_slots} service-slots were checked by more than one agent. These are independent "
            "observations, not duplicates: all are kept, and a slot counts as DOWN if any valid reading failed."
        )
    observations.append(
        f"Agents disagreed on up/down for {disagreements} slot(s) (after discarding invalid status codes)."
    )
    if invalid_only_slots:
        observations.append(
            f"{invalid_only_slots} slot(s) have only an invalid status reading; they are excluded from availability "
            "(neither up nor down)."
        )
    total_missing = sum(c["missing_slots"] for c in coverage.values())
    observations.append(
        f"{total_missing} expected 15-minute checks are missing across all services; gaps are not counted as downtime."
    )

    return {
        "rows_received": rows_received,
        "records_stored": len(records),
        "rows_rejected": sum(issues.counts[c] for c in ("malformed_row", "missing_service_id", "bad_timestamp")),
        "rows_skipped": issues.counts["blank_row"] + issues.counts["repeated_header"],
        "duplicates_removed": issues.counts["exact_duplicate"] + issues.counts["same_agent_duplicate"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": (end.date() - start.date()).days + 1,
        "services": sorted(per_service_slots),
        "agents": dict(Counter(r.agent for r in records)),
        "regions": dict(Counter(r.region for r in records)),
        "coverage": coverage,
        "multi_agent_slots": multi_agent_slots,
        "agent_disagreements": disagreements,
        "issues": issues.as_list(),
        "observations": observations,
    }
