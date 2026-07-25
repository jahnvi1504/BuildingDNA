"""Measure Tier 2 event completion across its logged simulated-time span."""

from __future__ import annotations

import json
import re

from ecoloop.config import PROJECT_ROOT, settings


TIME_PATTERN = re.compile(r"^day-(\d+)\s+(\d{2}):(\d{2})$")


def simulated_hour(value: str) -> float:
    match = TIME_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid simulation_time: {value!r}")
    day, hour, minute = (int(part) for part in match.groups())
    return (day - 1) * 24 + hour + minute / 60


def main() -> int:
    path = PROJECT_ROOT / "outputs" / "agent" / "reasoning.jsonl"
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not events:
        raise RuntimeError(f"No reasoning events found in {path}")

    values = [str(event["simulation_time"]) for event in events]
    first_hour = simulated_hour(values[0])
    last_hour = simulated_hour(values[-1])
    span_hours = max(0.0, last_hour - first_hour)
    interval_minutes = settings.ecoloop_reason_interval_minutes
    expected = int(span_hours * 60 // interval_minutes) + 1
    completion_rate = 100 * len(events) / expected
    result = {
        "reasoning_log": str(path.relative_to(PROJECT_ROOT)),
        "event_count": len(events),
        "first_simulation_time": values[0],
        "last_simulation_time": values[-1],
        "simulated_span_hours": round(span_hours, 4),
        "trigger_interval_minutes": interval_minutes,
        "expected_trigger_count": expected,
        "completion_rate_percent": round(completion_rate, 4),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
