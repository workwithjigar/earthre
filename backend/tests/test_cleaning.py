from datetime import datetime

import pytest

from app.cleaning import CsvValidationError, clean_csv, parse_latency, parse_status, parse_timestamp

HEADER = "service_id,service_name,timestamp,status_code,latency,latency_unit,agent,region\n"


def csv_bytes(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode()


def issue_counts(result) -> dict:
    return {i["code"]: i["count"] for i in result.report["issues"]}


@pytest.mark.parametrize(
    "raw, expected, flags",
    [
        ("2025-05-13T12:45:00Z", datetime(2025, 5, 13, 12, 45), []),
        ("1747909800", datetime(2025, 5, 22, 10, 30), ["epoch_timestamp"]),
        ("1747909800000", datetime(2025, 5, 22, 10, 30), ["epoch_timestamp"]),
        ("2025-05-16T19:00:00+05:30", datetime(2025, 5, 16, 13, 30), ["offset_timestamp"]),
        ("2025-05-16T13:30:00", datetime(2025, 5, 16, 13, 30), ["naive_timestamp"]),
    ],
)
def test_parse_timestamp(raw, expected, flags):
    assert parse_timestamp(raw) == (expected, flags)


def test_parse_timestamp_rejects_garbage():
    with pytest.raises(ValueError):
        parse_timestamp("yesterday")


@pytest.mark.parametrize(
    "raw, unit, expected, flags",
    [
        ("377", "ms", 377.0, []),
        ("0.717", "s", 717.0, ["seconds_latency"]),
        ("", "ms", None, ["missing_latency"]),
        ("-296", "ms", None, ["negative_latency"]),
        ("abc", "ms", None, ["invalid_latency"]),
        ("5", "fortnights", None, ["unknown_latency_unit"]),
        ("120", "", 120.0, ["missing_latency_unit"]),
    ],
)
def test_parse_latency(raw, unit, expected, flags):
    assert parse_latency(raw, unit) == (expected, flags)


@pytest.mark.parametrize(
    "raw, expected, flags",
    [("200", 200, []), ("503", 503, []), ("999", 999, ["invalid_status"]), ("", None, ["invalid_status"])],
)
def test_parse_status(raw, expected, flags):
    assert parse_status(raw) == (expected, flags)


def test_missing_required_column():
    with pytest.raises(CsvValidationError, match="timestamp"):
        clean_csv(b"service_id,status_code\nsvc-a,200\n")


def test_empty_file():
    with pytest.raises(CsvValidationError):
        clean_csv(b"   ")


def test_exact_duplicates_dropped():
    row = "svc-a,a-api,2025-05-13T12:45:00Z,200,100,ms,agent-1,ap-south-1"
    result = clean_csv(csv_bytes(row, row, row))
    assert len(result.records) == 1
    assert issue_counts(result)["exact_duplicate"] == 2


def test_same_agent_epoch_and_iso_copies_are_merged_keeping_latency():
    result = clean_csv(
        csv_bytes(
            "svc-a,a-api,1747909800,200,,ms,agent-1,ap-south-1",
            "svc-a,a-api,2025-05-22T10:30:00Z,200,107,ms,agent-1,ap-south-1",
        )
    )
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec.latency_ms == 107.0
    assert rec.raw_timestamp == "2025-05-22T10:30:00Z"
    assert "same_agent_duplicate" in rec.flags


def test_same_agent_conflict_keeps_failure():
    result = clean_csv(
        csv_bytes(
            "svc-a,a-api,2025-05-22T10:30:00Z,200,100,ms,agent-1,ap-south-1",
            "svc-a,a-api,1747909800,503,100,ms,agent-1,ap-south-1",
        )
    )
    assert [r.outcome for r in result.records] == ["down"]
    assert "conflicting_duplicate" in result.records[0].flags


def test_different_agents_are_both_kept():
    result = clean_csv(
        csv_bytes(
            "svc-a,a-api,2025-05-22T10:30:00Z,200,100,ms,agent-1,ap-south-1",
            "svc-a,a-api,2025-05-22T10:30:00Z,200,104,ms,agent-2,ap-south-1",
        )
    )
    assert len(result.records) == 2
    assert result.report["multi_agent_slots"] == 1


def test_invalid_status_is_kept_but_marked_invalid():
    result = clean_csv(csv_bytes("svc-a,a-api,2025-05-22T10:30:00Z,999,100,ms,agent-1,ap-south-1"))
    assert result.records[0].outcome == "invalid"
    assert result.records[0].status_code == 999


def test_bad_rows_rejected_and_records_sorted():
    result = clean_csv(
        csv_bytes(
            "svc-a,a-api,2025-05-22T11:00:00Z,200,100,ms,agent-1,ap-south-1",
            "svc-a,a-api,not-a-date,200,100,ms,agent-1,ap-south-1",
            "svc-a,a-api,2025-05-22T10:45:00Z,200",
            "",
            HEADER.strip(),
            "svc-a,a-api,2025-05-22T10:30:00Z,500,100,ms,agent-1,ap-south-1",
        )
    )
    counts = issue_counts(result)
    assert counts["bad_timestamp"] == 1
    assert counts["malformed_row"] == 1
    assert counts["blank_row"] == 1
    assert counts["repeated_header"] == 1
    assert [r.ts.hour * 60 + r.ts.minute for r in result.records] == [630, 660]
    assert result.report["coverage"]["svc-a"]["missing_slots"] == 1


def test_off_grid_timestamp_is_snapped():
    result = clean_csv(csv_bytes("svc-a,a-api,2025-05-22T10:31:10Z,200,100,ms,agent-1,ap-south-1"))
    assert result.records[0].ts == datetime(2025, 5, 22, 10, 30)
    assert "off_grid_timestamp" in result.records[0].flags


def test_service_name_mismatch_normalised():
    result = clean_csv(
        csv_bytes(
            "svc-a,a-api,2025-05-22T10:30:00Z,200,100,ms,agent-1,ap-south-1",
            "svc-a,a-api,2025-05-22T10:45:00Z,200,100,ms,agent-1,ap-south-1",
            "svc-a,A-API ,2025-05-22T11:00:00Z,200,100,ms,agent-1,ap-south-1",
        )
    )
    assert {r.service_name for r in result.records} == {"a-api"}
