from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

from ecoloop.carbon import grid_carbon_intensity
from ecoloop.config import Settings
from ecoloop.reason import ReasonAgent
from ecoloop.reflex import ReflexController
from ecoloop.state import LiveState, ZONES
from ecoloop.tools import ControlTools


COOLING_SCHEDULES = ("CLGSETP_SCH_NO_OPTIMUM", "CLGSETP_SCH_NO_OPTIMUM_w_SB")
HEATING_SCHEDULES = ("HTGSETP_SCH_NO_OPTIMUM", "HTGSETP_SCH_NO_OPTIMUM_w_SB")


def pmv_proxy(temperature_c: float) -> float:
    """Auditable operative-temperature PMV proxy used until full Fanger inputs are enabled."""
    return round(max(-3.0, min(3.0, (temperature_c - 24.0) * 0.35)), 3)


class EnergyPlusRunner:
    def __init__(self, settings: Settings, mode: str, output_dir: Path) -> None:
        if mode not in {"baseline", "agent"}:
            raise ValueError("mode must be baseline or agent")
        self.settings = settings
        self.mode = mode
        self.output_dir = output_dir
        self.state = LiveState(output_dir / "reasoning.jsonl")
        self.tools = ControlTools(
            state=self.state,
            idf_path=settings.resolved(settings.ecoloop_idf),
            idd_path=settings.resolved(settings.energyplus_home) / "Energy+.idd",
        )
        self.reflex = ReflexController(settings, self.state)
        self.reason = ReasonAgent(settings, self.state, self.tools)
        self.handles: dict[str, int] = {}
        self.last_energy_kwh = 0.0
        self.last_reason_minute = -1
        self.rows: list[dict[str, Any]] = []

    def _import_api(self) -> Any:
        home = self.settings.resolved(self.settings.energyplus_home)
        sys.path.insert(0, str(home))
        from pyenergyplus.api import EnergyPlusAPI

        return EnergyPlusAPI()

    def run(self) -> int:
        api = self._import_api()
        ep_state = api.state_manager.new_state()
        for zone in ZONES:
            api.exchange.request_variable(ep_state, "Zone Mean Air Temperature", zone)
        api.exchange.request_variable(ep_state, "Schedule Value", "BLDG_OCC_SCH_wo_SB")
        api.exchange.request_variable(
            ep_state, "Facility Total Electricity Demand Rate", "Whole Building"
        )

        def callback(state: Any) -> None:
            if not api.exchange.api_data_fully_ready(state):
                return
            if not self.handles:
                for zone in ZONES:
                    self.handles[f"temp:{zone}"] = api.exchange.get_variable_handle(
                        state, "Zone Mean Air Temperature", zone
                    )
                self.handles["electric_demand"] = api.exchange.get_variable_handle(
                    state, "Facility Total Electricity Demand Rate", "Whole Building"
                )
                self.handles["occupancy"] = api.exchange.get_variable_handle(
                    state, "Schedule Value", "BLDG_OCC_SCH_wo_SB"
                )
                for schedule in COOLING_SCHEDULES + HEATING_SCHEDULES:
                    self.handles[f"schedule:{schedule}"] = api.exchange.get_actuator_handle(
                        state, "Schedule:Compact", "Schedule Value", schedule
                    )
                invalid = {key: value for key, value in self.handles.items() if value < 0}
                if invalid:
                    self.state.add_error(f"Invalid EnergyPlus handles: {invalid}")
                    api.runtime.stop_simulation(state)
                    return

            temps = {
                zone: round(api.exchange.get_variable_value(state, self.handles[f"temp:{zone}"]), 4)
                for zone in ZONES
            }
            pmv = {zone: pmv_proxy(value) for zone, value in temps.items()}
            demand_w = max(
                0.0,
                api.exchange.get_variable_value(state, self.handles["electric_demand"]),
            )
            delta_energy = demand_w * api.exchange.system_time_step(state) / 1000.0
            self.last_energy_kwh += delta_energy
            energy_kwh = self.last_energy_kwh
            hour = api.exchange.hour(state)
            minute = int(api.exchange.minutes(state))
            day = api.exchange.day_of_year(state)
            occupied = api.exchange.get_variable_value(state, self.handles["occupancy"]) > 0.05
            intensity = grid_carbon_intensity(hour)

            if self.mode == "agent":
                decision = self.reflex.step(temps, occupied)
                for schedule in COOLING_SCHEDULES:
                    api.exchange.set_actuator_value(
                        state, self.handles[f"schedule:{schedule}"], decision.cooling_c
                    )
                for schedule in HEATING_SCHEDULES:
                    api.exchange.set_actuator_value(
                        state, self.handles[f"schedule:{schedule}"], decision.heating_c
                    )
            else:
                decision = self.reflex.step({}, False)
                decision.heating_c = 21.11 if occupied else 15.56
                decision.cooling_c = 23.89 if occupied else 29.44
                decision.intervened = False

            previous = self.state.snapshot()
            violation_increment = sum(1 for value in pmv.values() if occupied and abs(value) > 0.5)
            simulation_time = f"day-{day:03d} {hour:02d}:{minute:02d}"
            self.state.update(
                simulation_time=simulation_time,
                day_of_year=day,
                hour=hour,
                minute=minute,
                zone_temperatures_c=temps,
                pmv=pmv,
                energy_kwh=energy_kwh,
                carbon_intensity_kg_per_kwh=intensity,
                carbon_kg=previous["carbon_kg"] + delta_energy * intensity,
                heating_setpoint_c=decision.heating_c,
                cooling_setpoint_c=decision.cooling_c,
                comfort_violation_count=previous["comfort_violation_count"] + violation_increment,
                reflex_interventions=previous["reflex_interventions"] + int(decision.intervened),
            )
            snapshot = self.state.snapshot()
            row = {key: value for key, value in snapshot.items() if key not in {"zone_temperatures_c", "pmv"}}
            row.update({f"temp_{zone}": temps[zone] for zone in ZONES})
            row.update({f"pmv_{zone}": pmv[zone] for zone in ZONES})
            self.rows.append(row)

            absolute_minute = (day - 1) * 1440 + hour * 60 + minute
            if self.mode == "agent" and absolute_minute != self.last_reason_minute:
                if absolute_minute % self.settings.ecoloop_reason_interval_minutes == 0:
                    self.reason.observe(snapshot)
                    self.reason.trigger()
                    self.last_reason_minute = absolute_minute

        api.runtime.callback_after_predictor_before_hvac_managers(ep_state, callback)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        exit_code = api.runtime.run_energyplus(
            ep_state,
            [
                "-d",
                str(self.output_dir),
                "-w",
                str(self.settings.resolved(self.settings.ecoloop_epw)),
                str(self.settings.resolved(self.settings.ecoloop_idf)),
            ],
        )
        self._write_outputs(exit_code)
        api.state_manager.delete_state(ep_state)
        return exit_code

    def _write_outputs(self, exit_code: int) -> None:
        if self.mode == "agent" and not (self.output_dir / "reasoning.jsonl").exists():
            self.state.log_reason(
                {
                    "type": "reason_disabled",
                    "simulation_time": self.state.snapshot()["simulation_time"],
                    "actions": [],
                    "justification": (
                        "No rotated GROQ_API_KEY was configured. Tier 2 issued no actions; "
                        "Tier 1 completed the annual run independently."
                    ),
                }
            )
        telemetry_path = self.output_dir / "telemetry.csv"
        if self.rows:
            with telemetry_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
                writer.writeheader()
                writer.writerows(self.rows)
        summary = {
            "mode": self.mode,
            "exit_code": exit_code,
            "energyplus_version": "26.1.0-6f2e40d102",
            "telemetry_rows": len(self.rows),
            **self.state.snapshot(),
            "errors": self.state.get_errors(),
            "pmv_method": "operative-temperature proxy: clip((T-24)*0.35, -3, 3)",
        }
        (self.output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
