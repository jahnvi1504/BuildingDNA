from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ecoloop.carbon import grid_carbon_intensity
from ecoloop.healing import IDFSelfHealer
from ecoloop.state import LiveState, SetpointRequest


@dataclass(slots=True)
class ControlTools:
    state: LiveState
    idf_path: Path
    idd_path: Path

    def get_zone_temps(self) -> dict[str, float]:
        return self.state.snapshot()["zone_temperatures_c"]

    def get_pmv(self) -> dict[str, float]:
        return self.state.snapshot()["pmv"]

    def get_energy_kwh(self) -> float:
        return float(self.state.snapshot()["energy_kwh"])

    def get_grid_carbon_intensity(self) -> float:
        hour = int(self.state.snapshot()["hour"])
        return grid_carbon_intensity(hour)

    def set_setpoint(self, zone: str, value: float, kind: str = "cooling") -> dict[str, Any]:
        self.state.queue_setpoint(SetpointRequest(zone=zone, value_c=value, kind=kind))
        return {"queued": True, "zone": zone, "kind": kind, "value_c": value}

    def adjust_schedule(self, schedule_name: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
        self.state.adjust_schedule(schedule_name, ops)
        return {"queued": True, "schedule_name": schedule_name, "operations": ops}

    def get_error_log(self) -> list[str]:
        return self.state.get_errors()

    def patch_idf(self, diff: dict[str, Any]) -> dict[str, Any]:
        healer = IDFSelfHealer(self.idf_path, self.idd_path)
        result = healer.apply_patch(diff)
        self.state.log_reason({"type": "self_healing", **result})
        return result

