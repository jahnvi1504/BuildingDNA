import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_integrated_llm_action_reached_energyplus_actuator() -> None:
    proof = json.loads(
        (ROOT / "outputs" / "integrated-demo" / "integrated-proof.json").read_text()
    )

    assert proof["passed"] is True
    assert proof["mutating_tool_actions"]
    assert proof["mutating_tool_actions"][0]["tool"] == "set_setpoint"
    assert len(proof["actuator_samples"]) >= 8
    assert proof["readbacks_match"] is True


def test_self_healing_fault_patch_and_restart_are_preserved() -> None:
    proof = json.loads(
        (ROOT / "outputs" / "self-healing-demo" / "self-healing-proof.json").read_text()
    )
    fault_model = (ROOT / proof["fault_model"]).read_text()
    repaired_model = (ROOT / proof["repaired_model"]).read_text()

    assert proof["passed"] is True
    assert proof["fault"]["exit_code"] != 0
    assert proof["agent"]["tool"] == "patch_idf"
    assert proof["recovery"]["exit_code"] == 0
    assert proof["recovery"]["callback_count"] > 0
    assert proof["recovery"]["severe_or_fatal_errors"] == []
    assert "MISSING_ECOLOOP_COOLING_SCHEDULE" in fault_model
    assert "MISSING_ECOLOOP_COOLING_SCHEDULE" not in repaired_model
