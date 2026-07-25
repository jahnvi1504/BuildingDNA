"""Inject an IDF fault, let Groq patch it, restart, and verify recovery."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from eppy.modeleditor import IDF
from groq import Groq

from ecoloop.config import PROJECT_ROOT, settings
from ecoloop.state import LiveState
from ecoloop.tools import ControlTools


MODEL_DIR = PROJECT_ROOT / "models" / "runtime"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "self-healing-demo"
FAULT_MODEL = MODEL_DIR / "self_healing_fault.idf"
REPAIRED_MODEL = MODEL_DIR / "self_healing_repaired.idf"
PROOF_PATH = OUTPUT_DIR / "self-healing-proof.json"
BROKEN_SCHEDULE = "MISSING_ECOLOOP_COOLING_SCHEDULE"
VALID_SCHEDULE = "CLGSETP_SCH_NO_OPTIMUM"

PATCH_TOOL = {
    "type": "function",
    "function": {
        "name": "patch_idf",
        "description": "Apply a bounded field patch to the disposable runtime IDF.",
        "parameters": {
            "type": "object",
            "properties": {
                "diff": {
                    "type": "object",
                    "properties": {
                        "diagnosis": {"type": "string"},
                        "operations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "object_type": {"type": "string"},
                                    "object_name": {"type": "string"},
                                    "field": {"type": "string"},
                                    "value": {"type": ["string", "number"]},
                                },
                                "required": [
                                    "object_type",
                                    "object_name",
                                    "field",
                                    "value",
                                ],
                            },
                        },
                    },
                    "required": ["diagnosis", "operations"],
                }
            },
            "required": ["diff"],
        },
    },
}


def prepare_fault() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings.resolved(settings.ecoloop_idf), FAULT_MODEL)
    try:
        IDF.setiddname(str(settings.resolved(settings.energyplus_home) / "Energy+.idd"))
    except IDF.IDDAlreadySetError:
        pass
    idf = IDF(str(FAULT_MODEL))
    run_period = next(
        obj for obj in idf.idfobjects["RUNPERIOD"] if obj.Name == "RUNPERIOD 1"
    )
    run_period.End_Month = 1
    run_period.End_Day_of_Month = 2
    thermostat = next(
        obj
        for obj in idf.idfobjects["THERMOSTATSETPOINT:DUALSETPOINT"]
        if obj.Name == "Core_ZN Dual SP Control"
    )
    thermostat.Cooling_Setpoint_Temperature_Schedule_Name = BROKEN_SCHEDULE
    idf.saveas(str(FAULT_MODEL))
    shutil.copy2(FAULT_MODEL, REPAIRED_MODEL)


def run_model(model: Path, output: Path) -> tuple[int, int]:
    home = settings.resolved(settings.energyplus_home)
    if str(home) not in sys.path:
        sys.path.insert(0, str(home))
    from pyenergyplus.api import EnergyPlusAPI

    api = EnergyPlusAPI()
    ep_state = api.state_manager.new_state()
    callbacks = 0

    def callback(callback_state: Any) -> None:
        nonlocal callbacks
        if api.exchange.api_data_fully_ready(callback_state):
            callbacks += 1

    api.runtime.callback_after_predictor_before_hvac_managers(ep_state, callback)
    output.mkdir(parents=True, exist_ok=True)
    exit_code = api.runtime.run_energyplus(
        ep_state,
        [
            "-d",
            str(output),
            "-w",
            str(settings.resolved(settings.ecoloop_epw)),
            str(model),
        ],
    )
    api.state_manager.delete_state(ep_state)
    return exit_code, callbacks


def error_excerpt(error_path: Path) -> list[str]:
    lines = error_path.read_text(encoding="utf-8", errors="replace").splitlines()
    relevant = [
        line.strip()
        for line in lines
        if "** Severe **" in line or "** Fatal **" in line or BROKEN_SCHEDULE in line
    ]
    return relevant[-20:]


def main() -> int:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required for the self-healing demo")
    prepare_fault()
    failed_output = OUTPUT_DIR / "failed"
    repaired_output = OUTPUT_DIR / "repaired"
    failed_code, failed_callbacks = run_model(FAULT_MODEL, failed_output)
    errors = error_excerpt(failed_output / "eplusout.err")
    if failed_code == 0 or not errors:
        raise RuntimeError("Injected model did not produce the expected EnergyPlus failure")

    state = LiveState(OUTPUT_DIR / "reasoning.jsonl")
    for line in errors:
        state.add_error(line)
    tools = ControlTools(
        state,
        REPAIRED_MODEL,
        settings.resolved(settings.energyplus_home) / "Energy+.idd",
    )
    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Diagnose the EnergyPlus input failure and call patch_idf exactly once. "
                    "Patch only the named disposable thermostat object. The known-good cooling "
                    f"schedule is {VALID_SCHEDULE}. Do not propose source-code changes."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "error_log": state.get_errors(),
                        "disposable_model": str(REPAIRED_MODEL),
                        "affected_object": {
                            "object_type": "THERMOSTATSETPOINT:DUALSETPOINT",
                            "object_name": "Core_ZN Dual SP Control",
                            "field": "Cooling_Setpoint_Temperature_Schedule_Name",
                            "invalid_value": BROKEN_SCHEDULE,
                        },
                    }
                ),
            },
        ],
        tools=[PATCH_TOOL],
        tool_choice={"type": "function", "function": {"name": "patch_idf"}},
        temperature=0,
        max_completion_tokens=500,
    )
    call = response.choices[0].message.tool_calls[0]
    arguments = json.loads(call.function.arguments)
    patch_result = tools.patch_idf(**arguments)
    backup_path = Path(patch_result["backup"])
    patch_result["backup"] = backup_path.relative_to(PROJECT_ROOT).as_posix()
    repaired_code, repaired_callbacks = run_model(REPAIRED_MODEL, repaired_output)
    repaired_errors = error_excerpt(repaired_output / "eplusout.err")

    proof = {
        "model": settings.groq_model,
        "fault_model": FAULT_MODEL.relative_to(PROJECT_ROOT).as_posix(),
        "repaired_model": REPAIRED_MODEL.relative_to(PROJECT_ROOT).as_posix(),
        "fault": {
            "injected_value": BROKEN_SCHEDULE,
            "exit_code": failed_code,
            "callback_count": failed_callbacks,
            "errors": errors,
        },
        "agent": {
            "tool": call.function.name,
            "arguments": arguments,
            "patch_result": patch_result,
        },
        "recovery": {
            "exit_code": repaired_code,
            "callback_count": repaired_callbacks,
            "severe_or_fatal_errors": repaired_errors,
        },
    }
    passed = (
        failed_code != 0
        and call.function.name == "patch_idf"
        and patch_result["patched"]
        and repaired_code == 0
        and repaired_callbacks > 0
        and not repaired_errors
    )
    proof["passed"] = passed
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_PATH.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof, indent=2))
    print(f"SELF_HEALING_PROOF={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
