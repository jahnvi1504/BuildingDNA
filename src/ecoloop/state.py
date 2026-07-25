from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ZONES = ("Core_ZN", "Perimeter_ZN_1", "Perimeter_ZN_2", "Perimeter_ZN_3", "Perimeter_ZN_4")


@dataclass(slots=True)
class SetpointRequest:
    zone: str
    value_c: float
    kind: str = "cooling"
    source: str = "reason"


@dataclass(slots=True)
class Telemetry:
    simulation_time: str = ""
    day_of_year: int = 0
    hour: int = 0
    minute: int = 0
    zone_temperatures_c: dict[str, float] = field(default_factory=dict)
    pmv: dict[str, float] = field(default_factory=dict)
    energy_kwh: float = 0.0
    carbon_intensity_kg_per_kwh: float = 0.0
    carbon_kg: float = 0.0
    heating_setpoint_c: float = 21.0
    cooling_setpoint_c: float = 24.5
    comfort_violation_count: int = 0
    reflex_interventions: int = 0


class LiveState:
    def __init__(self, reasoning_log: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.telemetry = Telemetry()
        self.pending_requests: list[SetpointRequest] = []
        self.errors: list[str] = []
        self.schedule_adjustments: dict[str, list[dict[str, Any]]] = {}
        self.reasoning_log = reasoning_log

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self.telemetry)

    def update(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self.telemetry, key, value)

    def queue_setpoint(self, request: SetpointRequest) -> None:
        if request.zone not in ZONES and request.zone != "ALL":
            raise ValueError(f"Unknown conditioned zone: {request.zone}")
        if request.kind not in {"heating", "cooling"}:
            raise ValueError("kind must be 'heating' or 'cooling'")
        with self._lock:
            self.pending_requests.append(request)

    def drain_setpoints(self) -> list[SetpointRequest]:
        with self._lock:
            requests = self.pending_requests[:]
            self.pending_requests.clear()
            return requests

    def add_error(self, message: str) -> None:
        with self._lock:
            self.errors.append(message)
            self.errors = self.errors[-100:]

    def get_errors(self) -> list[str]:
        with self._lock:
            return self.errors[:]

    def adjust_schedule(self, name: str, operations: list[dict[str, Any]]) -> None:
        with self._lock:
            self.schedule_adjustments.setdefault(name, []).extend(operations)

    def log_reason(self, event: dict[str, Any]) -> None:
        if self.reasoning_log is None:
            return
        self.reasoning_log.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        with self._lock:
            with self.reasoning_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

