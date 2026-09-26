from datetime import datetime, timedelta

from app.stats import StatsConfig, build_slots, compute_monthly, compute_stats, credit_for, detect_incidents, percentile

T0 = datetime(2025, 4, 1)


def reading(i, outcome="up", latency=100.0, status=None, service="svc-a", agent="agent-1"):
    if status is None:
        status = {"up": 200, "down": 503, "invalid": None}[outcome]
    return {
        "service_id": service,
        "ts": T0 + timedelta(minutes=15 * i),
        "outcome": outcome,
        "status_code": status,
        "latency_ms": latency,
        "agent": agent,
    }


def test_slot_is_down_if_any_agent_failed():
    slots = build_slots([reading(0, "up"), reading(0, "down", agent="agent-2")])["svc-a"]
    assert [s.outcome for s in slots] == ["down"]


def test_invalid_only_slot_is_unknown_and_excluded():
    rows = [reading(0, "up"), reading(1, "invalid"), reading(2, "down")]
    svc = compute_stats(rows, {}, StatsConfig())["services"][0]
    assert (svc["up"], svc["down"], svc["unknown"]) == (1, 1, 1)
    assert svc["availability"] == 50.0


def test_invalid_reading_overridden_by_other_agent():
    slots = build_slots([reading(0, "invalid"), reading(0, "up", agent="agent-2")])["svc-a"]
    assert slots[0].outcome == "up"


def test_percentile():
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([], 95) is None


def test_credit_tiers():
    cfg = StatsConfig()
    assert credit_for(99.95, cfg) == 0
    assert credit_for(99.5, cfg) == 10
    assert credit_for(98.0, cfg) == 25
    assert credit_for(90.0, cfg) == 100


def test_incident_merges_small_gaps_and_ignores_blips():
    rows = [reading(i) for i in range(40)]
    for i in (5, 6, 8, 9):  # one burst with a single healthy check in the middle
        rows[i] = reading(i, "down")
    rows[20] = reading(20, "down")  # isolated blip
    rows[30] = reading(30, "up", latency=2500)  # slow but 200
    rows[31] = reading(31, "up", latency=2600)
    rows[32] = reading(32, "down", latency=2700)
    incidents = detect_incidents(build_slots(rows)["svc-a"], StatsConfig())
    assert [(i["failed_checks"], i["slow_checks"], i["duration_minutes"]) for i in incidents] == [
        (4, 0, 75),
        (1, 2, 45),
    ]


def test_error_budget_and_sla():
    rows = [reading(i) for i in range(2000)]
    rows[0] = reading(0, "down")
    svc = compute_stats(rows, {}, StatsConfig())["services"][0]
    assert svc["sla_met"] is True  # 1/2000 down = 99.95%
    assert svc["downtime_minutes"] == 15
    assert svc["allowed_downtime_minutes"] == 30.0
    assert svc["error_budget_used_pct"] == 50.0


def test_monthly_split_and_partial_flag():
    rows = [reading(i) for i in range(96 * 3)]  # 3 days
    rows_other_month = [dict(r, ts=r["ts"] - timedelta(days=2)) for r in rows]
    monthly = compute_monthly(rows_other_month, {"svc-a": "a-api"}, StatsConfig())
    assert [(m["month"], m["days_observed"], m["partial"]) for m in monthly] == [
        ("2025-03", 2, True),
        ("2025-04", 1, True),
    ]
