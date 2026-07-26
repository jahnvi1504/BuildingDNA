import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ecoloop.config import Settings
from ecoloop.decision import (
    normalize_reasoning_record,
    parse_structured_decision,
    reasoning_card_html,
)
from ecoloop.reason import ReasonAgent
from ecoloop.response_quality import NON_ACTIONABLE_LABEL
from ecoloop.state import LiveState
from ecoloop.tools import ControlTools


def valid_decision() -> dict[str, Any]:
    return {
        "diagnosis": "Core zone is slightly warm while occupied.",
        "recommended_action": "Set Core_ZN cooling to 25.0°C.",
        "reason": "A small cooling adjustment addresses measured PMV without a large drift.",
        "optimization_priority": "comfort_first",
        "confidence": 0.82,
        "expected_impact": {
            "energy": "Small increase expected.",
            "comfort": "Warm discomfort should decrease.",
        },
        "action": {
            "tool": "set_setpoint",
            "arguments": {
                "zone": "Core_ZN",
                "value": 25.0,
                "kind": "cooling",
            },
        },
    }


def test_parses_valid_structured_response_with_markdown_fences() -> None:
    decision = parse_structured_decision(
        "```json\n" + json.dumps(valid_decision()) + "\n```"
    )

    assert decision.confidence == 0.82
    assert decision.action is not None
    assert decision.action.arguments.zone == "Core_ZN"


@pytest.mark.parametrize(
    "verbose",
    (
        "This is a JSON data dump from a building simulation.",
        "Here's a breakdown of the key fields in the telemetry.",
        "The data contains energy and temperature values.",
        "Without more context, no conclusion can be reached.",
        "1. Simulation time\n2. Zone temperatures\n3. PMV values",
    ),
)
def test_rejects_verbose_json_schema_explanations(verbose: str) -> None:
    payload = valid_decision()
    payload["diagnosis"] = verbose

    with pytest.raises(ValueError, match="generic telemetry/schema explanation"):
        parse_structured_decision(json.dumps(payload))


class FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        content = self.contents.pop(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content, tool_calls=None)
                )
            ]
        )


def reason_agent(
    monkeypatch: Any,
    responses: list[str],
) -> tuple[ReasonAgent, LiveState, FakeCompletions]:
    completions = FakeCompletions(responses)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(OpenAI=lambda **_: client),
    )
    state = LiveState()
    state.update(
        simulation_time="day-001 12:00",
        occupied=True,
        zone_temperatures_c={"Core_ZN": 24.5},
        pmv={"Core_ZN": 0.175},
        energy_kwh=12.0,
        cooling_setpoint_c=25.4,
    )
    settings = Settings(_env_file=None, ai_debate_mode="off")
    tools = ControlTools(state, Path("model.idf"), Path("Energy+.idd"))
    agent = ReasonAgent(settings, state, tools)
    agent.observe(state.snapshot())
    return agent, state, completions


def test_malformed_response_retries_once_then_falls_back(monkeypatch: Any) -> None:
    agent, state, completions = reason_agent(
        monkeypatch,
        ["not-json", "still not-json"],
    )

    event = agent.run_once()

    assert len(completions.calls) == 2
    assert event["fallback_used"] is True
    assert event["diagnosis"] == NON_ACTIONABLE_LABEL
    assert event["safety_status"] == "deterministic_fallback"
    assert state.drain_setpoints() == []


def test_repair_attempt_can_return_a_valid_decision(monkeypatch: Any) -> None:
    agent, state, completions = reason_agent(
        monkeypatch,
        ["This is a JSON data dump.", json.dumps(valid_decision())],
    )

    event = agent.run_once()

    assert len(completions.calls) == 2
    assert event["fallback_used"] is False
    assert event["applied_action"]["tool"] == "set_setpoint"
    assert {
        "simulation_time",
        "event_type",
        "optimization_priority",
        "diagnosis",
        "recommended_action",
        "reason",
        "expected_impact",
        "confidence",
        "safety_status",
        "applied_action",
        "fallback_used",
    }.issubset(event)
    assert state.drain_setpoints()[0].value_c == 25.0
    first_payload = json.loads(completions.calls[0]["messages"][1]["content"])
    assert "compact_context" in first_payload
    assert "recent_telemetry" not in first_payload


def test_dashboard_card_hides_full_raw_output_and_sanitizes_generic_legacy() -> None:
    raw = "This is a JSON data dump. " + "private verbose detail " * 80
    record = {
        "simulation_time": "day-001 12:00",
        "type": "reason_action",
        "justification": raw,
    }

    card = reasoning_card_html(record, "Balanced")
    normalized = normalize_reasoning_record(record)

    assert raw not in card
    assert "private verbose detail" not in card
    assert NON_ACTIONABLE_LABEL in card
    assert normalized["fallback_used"] is True


def test_legacy_concise_entry_remains_readable() -> None:
    record = {
        "simulation_time": "day-002 14:00",
        "type": "reason_action",
        "justification": "PMV is comfortable; hold current setpoints.",
        "actions": [],
    }

    card = reasoning_card_html(record, "Balanced")

    assert "PMV is comfortable; hold current setpoints." in card
    assert "Legacy entry retained" in card


def test_long_legacy_text_is_truncated_and_html_escaped() -> None:
    dangerous = "<script>alert('x')</script>" + "A" * 1000
    card = reasoning_card_html(
        {
            "simulation_time": "day-003 10:00",
            "type": "reason_action",
            "justification": dangerous,
        },
        "<b>Unsafe mode</b>",
    )

    assert "<script>" not in card
    assert "<b>Unsafe mode</b>" not in card
    assert "&lt;script&gt;" in card
    assert "&lt;b&gt;Unsafe mode&lt;/b&gt;" in card
    assert "…" in card
    assert len(card) < 1800
