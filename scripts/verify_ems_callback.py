"""Prove a live EnergyPlus sensor read and actuator write in one run.

This is intentionally independent of the Eco-Loop agent. It is the project's
de-risk gate: no higher-level control code should be trusted until this script
passes against the locally installed EnergyPlus version.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EPLUS_HOME = (
    PROJECT_ROOT
    / ".local"
    / "EnergyPlus-26.1.0"
    / "EnergyPlus-26.1.0-6f2e40d102-Windows-x86_64"
)


def energyplus_home() -> Path:
    configured = os.getenv("ENERGYPLUS_HOME")
    path = Path(configured) if configured else DEFAULT_EPLUS_HOME
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not (path / "energyplus.exe").is_file():
        raise FileNotFoundError(f"EnergyPlus executable not found under {path}")
    return path


def build_parser(home: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--idf",
        type=Path,
        default=home / "ExampleFiles" / "5ZoneAirCooled.idf",
    )
    parser.add_argument(
        "--weather",
        type=Path,
        default=home
        / "WeatherData"
        / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "callback-proof",
    )
    parser.add_argument("--timesteps", type=int, default=12)
    return parser


def main() -> int:
    home = energyplus_home()
    sys.path.insert(0, str(home))
    from pyenergyplus.api import EnergyPlusAPI

    args = build_parser(home).parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    api.exchange.request_variable(state, "Zone Mean Air Temperature", "SPACE1-1")

    handles: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    failure: str | None = None

    def callback(callback_state: Any) -> None:
        nonlocal failure
        if api.exchange.api_data_fully_ready(callback_state) is False:
            return

        if not handles:
            handles["temperature"] = api.exchange.get_variable_handle(
                callback_state, "Zone Mean Air Temperature", "SPACE1-1"
            )
            handles["cooling_schedule"] = api.exchange.get_actuator_handle(
                callback_state,
                "Schedule:Compact",
                "Schedule Value",
                "Clg-SetP-Sch",
            )
            bad = {name: value for name, value in handles.items() if value < 0}
            if bad:
                failure = f"Invalid API handles: {bad}"
                api.runtime.stop_simulation(callback_state)
                return

        temperature = api.exchange.get_variable_value(
            callback_state, handles["temperature"]
        )
        requested_setpoint = 24.0 if len(samples) % 2 == 0 else 25.0
        api.exchange.set_actuator_value(
            callback_state, handles["cooling_schedule"], requested_setpoint
        )
        observed_setpoint = api.exchange.get_actuator_value(
            callback_state, handles["cooling_schedule"]
        )
        samples.append(
            {
                "day_of_year": api.exchange.day_of_year(callback_state),
                "hour": api.exchange.hour(callback_state),
                "minutes": api.exchange.minutes(callback_state),
                "zone": "SPACE1-1",
                "zone_temperature_c": round(temperature, 4),
                "requested_cooling_setpoint_c": requested_setpoint,
                "observed_actuator_value_c": round(observed_setpoint, 4),
            }
        )
        if len(samples) >= args.timesteps:
            api.runtime.stop_simulation(callback_state)

    api.runtime.callback_begin_system_timestep_before_predictor(state, callback)
    exit_code = api.runtime.run_energyplus(
        state,
        [
            "-d",
            str(args.output),
            "-w",
            str(args.weather.resolve()),
            str(args.idf.resolve()),
        ],
    )

    proof = {
        "energyplus_version": "26.1.0-6f2e40d102",
        "api_version": api.api_version(),
        "exit_code": exit_code,
        "sensor_handle": handles.get("temperature"),
        "actuator_handle": handles.get("cooling_schedule"),
        "sample_count": len(samples),
        "samples": samples,
        "failure": failure,
    }
    proof_path = args.output / "callback-proof.json"
    proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    api.state_manager.delete_state(state)

    values_match = all(
        sample["requested_cooling_setpoint_c"]
        == sample["observed_actuator_value_c"]
        for sample in samples
    )
    passed = failure is None and len(samples) >= args.timesteps and values_match
    print(json.dumps(proof, indent=2))
    print(f"CALLBACK_PROOF={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
