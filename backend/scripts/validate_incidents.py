"""Run the cleaning + stats pipeline over the sample CSVs and compare the
detected incidents with dataset_incident_log.json (the ground truth).

Usage (from backend/):  python -m scripts.validate_incidents ../
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from app.cleaning import clean_csv
from app.stats import StatsConfig, compute_stats


def expected_windows(entry: dict) -> list[tuple[str, datetime, datetime]]:
    start = datetime.fromisoformat(entry["start"])
    out = []
    for key, desc in entry["incidents"].items():
        service, day = re.match(r"(\S+) day (\d+)", key).groups()
        first, last = map(int, re.match(r"check-points (\d+)-(\d+)", desc).groups())
        base = start + timedelta(days=int(day))
        out.append((service, base + timedelta(minutes=15 * first), base + timedelta(minutes=15 * (last + 1))))
    return out


def main(data_dir: str) -> int:
    root = Path(data_dir)
    truth = json.loads((root / "dataset_incident_log.json").read_text())
    failures = 0
    for filename, entry in truth.items():
        result = clean_csv((root / filename).read_bytes())
        rows = [asdict(r) for r in result.records]
        stats = compute_stats(rows, {}, StatsConfig())
        detected = stats["incidents"]
        print(f"\n== {filename}: {result.report['days']} days (log says {entry['days']}), "
              f"{len(detected)} incidents detected, {len(entry['incidents'])} expected")
        for service, start, end in expected_windows(entry):
            hits = [
                i for i in detected
                if i["service_id"] == service
                and datetime.fromisoformat(i["start"]) < end
                and datetime.fromisoformat(i["end"]) > start
            ]
            status = "OK  " if hits else "MISS"
            failures += not hits
            print(f"  {status} expected {service} {start:%m-%d %H:%M}-{end:%H:%M}  ->  "
                  + ", ".join(f"{i['start'][5:16]}-{i['end'][11:16]}" for i in hits))
        expected = expected_windows(entry)
        for i in detected:
            s, e = datetime.fromisoformat(i["start"]), datetime.fromisoformat(i["end"])
            if not any(svc == i["service_id"] and s < ee and e > ss for svc, ss, ee in expected):
                print(f"  EXTRA {i['service_id']} {i['start']} {i['duration_minutes']}min "
                      f"failed={i['failed_checks']} slow={i['slow_checks']}")
        for svc in stats["services"]:
            print(f"    {svc['service_id']:13} avail={svc['availability']:.3f}%  down={svc['down']:3}  "
                  f"unknown={svc['unknown']}  p95={svc['latency_p95_ms']}ms")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ".."))
