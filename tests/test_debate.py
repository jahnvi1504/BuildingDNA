import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ecoloop.config import Settings
from ecoloop.debate import DebateEngine, DebateMode
from ecoloop.reason import ReasonAgent
from ecoloop.state import LiveState
from ecoloop.tools import ControlTools


def perspective(
    role: str,
    *,
    action: dict[str, Any] | None = None,
    saving: float | None = 4.0,
) -> dict[str, Any]:
    return {
        "role": role,
        "recommendation": f"{role} concise recommendation.",
        "proposed_action": action,
        "expected_energy_saving_percent": saving,
        "expected_comfort_impact": "Estimated neutral comfort impact.",
        "risks": ["Estimate requires simulation validation."],
        "confidence": 0.7,
    }


def action(value: float = 25.0) -> dict[str, Any]:
    return {
        "tool": "set_setpoint",
        "arguments": {"zone": "Core_ZN", "value": value, "kind": "cooling"},
    }


class FakeCompletions:
    def __init__(self, payloads: list[dict[str, Any] | str]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


def engine(
    payloads: list[dict[str, Any] | str],
) -> tuple[DebateEngine, LiveState, FakeCompletions]:
    settings = Settings(_env_file=None, ai_debate_mode="compact")
    state = LiveState()
    state.update(
        simulation_time="day-001 12:00",
        occupied=True,
        zone_temperatures_c={"Core_ZN": 24.5},
        pmv={"Core_ZN": 0.175},
        cooling_setpoint_c=25.4,
    )
    tools = ControlTools(state, Path("model.idf"), Path("Energy+.idd"))
    completions = FakeCompletions(payloads)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return DebateEngine(settings, tools, client), state, completions


def compact_payload(final_action: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "optimization_priority": "balanced",
        "energy_saver": perspective("Energy Saver", action=action(26.0)),
        "comfort_guardian": perspective("Comfort Guardian", action=None, saving=None),
        "arbiter": perspective("BuildingDNA Arbiter", action=final_action),
        "final_action": final_action,
        "consensus_summary": "Use the bounded compromise.",
        "disagreement_summary": "Comfort Guardian preferred less drift.",
        "estimated_energy_saving_percent": 3.0,
        "estimated_comfort_impact": "Estimated maintained comfort.",
        "confidence": 0.75,
    }


def test_compact_debate_executes_only_arbiter_final_action() -> None:
    debate_engine, state, completions = engine([compact_payload(action(25.0))])

    result, actions = debate_engine.run([state.snapshot()], DebateMode.COMPACT)

    queued = state.drain_setpoints()
    assert len(completions.calls) == 1
    assert len(queued) == 1
    assert queued[0].value_c == 25.0
    assert actions[0]["source"] == "debate_arbiter"
    assert result.fallback_used is False


def test_full_debate_uses_three_role_specific_requests() -> None:
    energy = perspective("Energy Saver", action=action(26.0))
    comfort = perspective("Comfort Guardian", action=None, saving=None)
    arbiter = perspective("BuildingDNA Arbiter", action=action(25.0))
    debate_engine, state, completions = engine([energy, comfort, arbiter])

    result, actions = debate_engine.run([state.snapshot()], DebateMode.FULL)

    assert len(completions.calls) == 3
    assert result.final_action is not None
    assert actions[0]["arguments"]["value"] == 25.0
    assert state.drain_setpoints()[0].value_c == 25.0


def test_malformed_debate_falls_back_without_queueing_action() -> None:
    debate_engine, state, _ = engine(["not-json"])

    result, actions = debate_engine.run([state.snapshot()], DebateMode.COMPACT)

    assert result.fallback_used is True
    assert result.final_action is None
    assert actions == []
    assert state.drain_setpoints() == []
    assert "deterministic Tier 1" in result.consensus_summary


def test_compact_debate_defaults_bookkeeping_fields_from_context() -> None:
    payload = compact_payload(action(25.0))
    payload.pop("optimization_priority")
    payload.pop("confidence")
    debate_engine, state, _ = engine([payload])

    result, _ = debate_engine.run(
        [
            {
                **state.snapshot(),
                "macro_policy": {"mode": "Comfort Priority"},
            }
        ],
        DebateMode.COMPACT,
    )

    assert result.optimization_priority.value == "comfort_first"
    assert result.confidence == result.arbiter.confidence
    assert result.fallback_used is False


def test_unknown_zone_falls_back_before_existing_control_tool() -> None:
    invalid = action(25.0)
    invalid["arguments"]["zone"] = "Unknown Zone"
    debate_engine, state, _ = engine([compact_payload(invalid)])

    result, actions = debate_engine.run([state.snapshot()], DebateMode.COMPACT)

    assert result.fallback_used is True
    assert actions == []
    assert state.drain_setpoints() == []


def test_debate_mode_defaults_to_compact_and_accepts_off() -> None:
    assert Settings(_env_file=None).ai_debate_mode == "compact"
    assert Settings(_env_file=None, ai_debate_mode="off").ai_debate_mode == "off"


def test_replay_preview_never_queues_the_arbiter_action() -> None:
    debate_engine, state, _ = engine([compact_payload(action(25.0))])

    result, actions = debate_engine.run(
        [state.snapshot()],
        DebateMode.COMPACT,
        execute_action=False,
    )

    assert result.final_action is not None
    assert actions == []
    assert state.drain_setpoints() == []


def test_off_mode_preserves_existing_single_agent_flow(monkeypatch: Any) -> None:
    payload = {
        "diagnosis": "All measured zones are within the active comfort target.",
        "recommended_action": "Hold current setpoints.",
        "reason": "No measured condition justifies a supervisory change.",
        "optimization_priority": "balanced",
        "confidence": 0.9,
        "expected_impact": {
            "energy": "No immediate change expected.",
            "comfort": "Comfort maintained.",
        },
        "action": None,
    }
    message = SimpleNamespace(
        content=json.dumps(payload),
        tool_calls=None,
    )
    completions = SimpleNamespace(
        create=lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=message)]
        )
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(OpenAI=lambda **_: client),
    )
    settings = Settings(_env_file=None, ai_debate_mode="off")
    state = LiveState()
    state.update(simulation_time="day-001 12:00")
    tools = ControlTools(state, Path("model.idf"), Path("Energy+.idd"))
    reason = ReasonAgent(settings, state, tools)
    reason.observe(state.snapshot())

    event = reason.run_once()

    assert event["type"] == "reason_action"
    assert event["actions"] == []
    assert event["fallback_used"] is False
    assert event["diagnosis"] == payload["diagnosis"]
