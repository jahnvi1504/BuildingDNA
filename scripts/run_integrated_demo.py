"""Prove local LLM tool calls change actuators inside one live EnergyPlus process."""

from __future__ import annotations

import json
import shutil
import sys
from typing import Any

from eppy.modeleditor import IDF
from openai import OpenAI

from ecoloop.carbon import grid_carbon_intensity
from ecoloop.config import PROJECT_ROOT, settings
from ecoloop.reason import TOOL_SCHEMAS
from ecoloop.reflex import ReflexController
from ecoloop.simulation import COOLING_SCHEDULES, HEATING_SCHEDULES, pmv_proxy
from ecoloop.state import LiveState, ZONES
from ecoloop.tools import ControlTools


MODEL_DIR = PROJECT_ROOT / "models" / "runtime"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "integrated-demo"
MODEL_PATH = MODEL_DIR / "integrated_llm_demo.idf"
PROOF_PATH = OUTPUT_DIR / "integrated-proof.json"
SETPOINT_TOOL = next(
    schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "set_setpoint"
)


def prepare_model() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings.resolved(settings.ecoloop_idf), MODEL_PATH)
    try:
        IDF.setiddname(str(settings.resolved(settings.energyplus_home) / "Energy+.idd"))
    except IDF.IDDAlreadySetError:
        pass
    idf = IDF(str(MODEL_PATH))
    run_period = next(
        obj for obj in idf.idfobjects["RUNPERIOD"] if obj.Name == "RUNPERIOD 1"
    )
    run_period.End_Month = 1
    run_period.End_Day_of_Month = 2
    idf.saveas(str(MODEL_PATH))


def main() -> int:
    prepare_model()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reasoning_path = OUTPUT_DIR / "reasoning.jsonl"
    reasoning_path.unlink(missing_ok=True)

    home = settings.resolved(settings.energyplus_home)
    sys.path.insert(0, str(home))
    from pyenergyplus.api import EnergyPlusAPI

    api = EnergyPlusAPI()
    ep_state = api.state_manager.new_state()
    state = LiveState(reasoning_path)
    tools = ControlTools(state, MODEL_PATH, home / "Energy+.idd")
    reflex = ReflexController(settings, state)
    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    handles: dict[str, int] = {}
    proof: dict[str, Any] = {
        "model": MODEL_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "model_name": settings.llm_model,
        "reason_event": None,
        "actuator_samples": [],
        "failure": None,
    }
    reasoning_complete = False

    for zone in ZONES:
        api.exchange.request_variable(ep_state, "Zone Mean Air Temperature", zone)
    api.exchange.request_variable(
        ep_state, "Facility Total Electricity Demand Rate", "Whole Building"
    )

    def callback(callback_state: Any) -> None:
        nonlocal reasoning_complete
        if not api.exchange.api_data_fully_ready(callback_state):
            return
        if not handles:
            for zone in ZONES:
                handles[f"temp:{zone}"] = api.exchange.get_variable_handle(
                    callback_state, "Zone Mean Air Temperature", zone
                )
            handles["demand"] = api.exchange.get_variable_handle(
                callback_state, "Facility Total Electricity Demand Rate", "Whole Building"
            )
            for schedule in COOLING_SCHEDULES + HEATING_SCHEDULES:
                handles[f"schedule:{schedule}"] = api.exchange.get_actuator_handle(
                    callback_state, "Schedule:Compact", "Schedule Value", schedule
                )
            invalid = {name: value for name, value in handles.items() if value < 0}
            if invalid:
                proof["failure"] = f"Invalid handles: {invalid}"
                api.runtime.stop_simulation(callback_state)
                return

        temps = {
            zone: round(
                api.exchange.get_variable_value(callback_state, handles[f"temp:{zone}"]),
                4,
            )
            for zone in ZONES
        }
        pmv = {zone: pmv_proxy(value) for zone, value in temps.items()}
        hour = api.exchange.hour(callback_state)
        minute = int(api.exchange.minutes(callback_state))
        state.update(
            simulation_time=f"day-{api.exchange.day_of_year(callback_state):03d} "
            f"{hour:02d}:{minute:02d}",
            day_of_year=api.exchange.day_of_year(callback_state),
            hour=hour,
            minute=minute,
            zone_temperatures_c=temps,
            pmv=pmv,
            energy_kwh=max(
                0.0,
                api.exchange.get_variable_value(callback_state, handles["demand"]) / 1000,
            ),
            carbon_intensity_kg_per_kwh=grid_carbon_intensity(hour),
        )

        if not reasoning_complete:
            if hour < 14:
                return
            telemetry = {
                **state.snapshot(),
                "demonstration_constraint": (
                    "Issue one conservative cooling setpoint between 24.0C and "
                    "26.0C. Tier 1 will independently validate it."
                ),
            }
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "You supervise a live office. Use the required set_setpoint tool "
                        "exactly once based on the supplied telemetry. Choose a valid zone, "
                        "kind='cooling', and a value from 24.0C through 26.0C."
                    ),
                },
                {"role": "user", "content": json.dumps(telemetry)},
            ]
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=[SETPOINT_TOOL],
                tool_choice={"type": "function", "function": {"name": "set_setpoint"}},
                temperature=0,
                max_completion_tokens=250,
            )
            message = response.choices[0].message
            call = message.tool_calls[0]
            parsed = json.loads(call.function.arguments or "{}")
            arguments = {
                key: value
                for key, value in parsed.items()
                if key in {"zone", "value", "kind"}
            }
            result = tools.set_setpoint(**arguments)
            messages.extend(
                [
                    message.model_dump(exclude_none=True),
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result),
                    },
                ]
            )
            final = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                temperature=0,
                max_completion_tokens=160,
            )
            event = {
                "type": "reason_action",
                "simulation_time": state.snapshot()["simulation_time"],
                "model": settings.llm_model,
                "actions": [
                    {
                        "tool": call.function.name,
                        "arguments": arguments,
                        "result": result,
                    }
                ],
                "justification": final.choices[0].message.content
                or "Local LLM action applied.",
            }
            state.log_reason(event)
            proof["reason_event"] = event
            reasoning_complete = True

        decision = reflex.step(temps, occupied=True)
        for schedule in COOLING_SCHEDULES:
            api.exchange.set_actuator_value(
                callback_state, handles[f"schedule:{schedule}"], decision.cooling_c
            )
        for schedule in HEATING_SCHEDULES:
            api.exchange.set_actuator_value(
                callback_state, handles[f"schedule:{schedule}"], decision.heating_c
            )
        proof["actuator_samples"].append(
            {
                "simulation_time": state.snapshot()["simulation_time"],
                "heating_requested_c": decision.heating_c,
                "cooling_requested_c": decision.cooling_c,
                "heating_readback_c": api.exchange.get_actuator_value(
                    callback_state, handles[f"schedule:{HEATING_SCHEDULES[0]}"]
                ),
                "cooling_readback_c": api.exchange.get_actuator_value(
                    callback_state, handles[f"schedule:{COOLING_SCHEDULES[0]}"]
                ),
                "reflex_reason": decision.reason,
            }
        )
        if len(proof["actuator_samples"]) >= 8:
            api.runtime.stop_simulation(callback_state)

    api.runtime.callback_after_predictor_before_hvac_managers(ep_state, callback)
    exit_code = api.runtime.run_energyplus(
        ep_state,
        [
            "-d",
            str(OUTPUT_DIR),
            "-w",
            str(settings.resolved(settings.ecoloop_epw)),
            str(MODEL_PATH),
        ],
    )
    proof["exit_code"] = exit_code
    api.state_manager.delete_state(ep_state)

    actions = (proof["reason_event"] or {}).get("actions", [])
    mutating_actions = [
        action for action in actions if action["tool"] in {"set_setpoint", "adjust_schedule"}
    ]
    readbacks_match = all(
        abs(sample["heating_requested_c"] - sample["heating_readback_c"]) < 1e-6
        and abs(sample["cooling_requested_c"] - sample["cooling_readback_c"]) < 1e-6
        for sample in proof["actuator_samples"]
    )
    passed = (
        proof["failure"] is None
        and bool(mutating_actions)
        and len(proof["actuator_samples"]) >= 8
        and readbacks_match
    )
    proof["mutating_tool_actions"] = mutating_actions
    proof["readbacks_match"] = readbacks_match
    proof["passed"] = passed
    PROOF_PATH.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof, indent=2))
    print(f"INTEGRATED_LLM_ENERGYPLUS_PROOF={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
