from __future__ import annotations

import json
import threading
from collections import deque
from typing import Any

from ecoloop.config import Settings
from ecoloop.state import LiveState
from ecoloop.tools import ControlTools


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_zone_temps",
            "description": "Return current conditioned-zone temperatures in Celsius.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pmv",
            "description": "Return current thermal comfort PMV estimates by zone.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_energy_kwh",
            "description": "Return cumulative facility electricity in kWh.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_grid_carbon_intensity",
            "description": "Return current grid intensity in kgCO2e/kWh.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_setpoint",
            "description": "Queue a supervisory setpoint; the reflex layer clamps it for safety.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone": {"type": "string"},
                    "value": {"type": "number"},
                    "kind": {"type": "string", "enum": ["heating", "cooling"]},
                },
                "required": ["zone", "value", "kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_schedule",
            "description": "Queue bounded schedule operations for the live controller.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule_name": {"type": "string"},
                    "ops": {
                        "type": "array",
                        "items": {"type": "object"},
                        "maxItems": 4,
                    },
                },
                "required": ["schedule_name", "ops"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_error_log",
            "description": "Return recent EnergyPlus and controller errors.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_idf",
            "description": (
                "Patch an allow-listed IDF field after diagnosing a severe error. "
                "Use only when get_error_log shows a concrete model fault."
            ),
            "parameters": {
                "type": "object",
                "properties": {"diff": {"type": "object"}},
                "required": ["diff"],
            },
        },
    },
]

MUTATING_TOOLS = {"set_setpoint", "adjust_schedule", "patch_idf"}
MAX_TOOL_ROUNDS = 3
MAX_ACTIONS = 2
TOOL_PARAMETER_NAMES = {
    schema["function"]["name"]: set(
        schema["function"]["parameters"].get("properties", {})
    )
    for schema in TOOL_SCHEMAS
}


class ReasonAgent:
    def __init__(self, settings: Settings, state: LiveState, tools: ControlTools) -> None:
        self.settings = settings
        self.state = state
        self.tools = tools
        self.windows: deque[dict[str, Any]] = deque(maxlen=12)
        self._running = False
        self._lock = threading.Lock()

    def observe(self, snapshot: dict[str, Any]) -> None:
        self.windows.append(snapshot)

    def trigger(self) -> bool:
        if not self.settings.ecoloop_reason_enabled:
            return False
        with self._lock:
            if self._running:
                return False
            self._running = True
        threading.Thread(target=self._run, daemon=True, name="ecoloop-reason").start()
        return True

    def run_once(self) -> dict[str, Any]:
        """Run one synchronous reasoning cycle; useful for startup checks and tests."""
        if not self.settings.ecoloop_reason_enabled:
            raise RuntimeError("Tier 2 is disabled by ECOLOOP_REASON_ENABLED")
        return self._reason()

    def _run(self) -> None:
        try:
            self._reason()
        except Exception as exc:
            self.state.add_error(f"Reason layer error: {exc}")
            self.state.log_reason(
                {
                    "type": "reason_failure",
                    "simulation_time": self.state.snapshot()["simulation_time"],
                    "justification": f"Tier 2 unavailable; Tier 1 continued safely: {exc}",
                }
            )
        finally:
            with self._lock:
                self._running = False

    def _reason(self) -> dict[str, Any]:
        from openai import OpenAI

        client = OpenAI(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are the Tier 2 supervisor for a live EnergyPlus office. Minimize electricity "
                    "and carbon while occupied-zone PMV remains between -0.5 and +0.5. Tier 1 owns "
                    "hard safety and clamps every request. Inspect telemetry before acting. Make no "
                    "more than two mutating tool calls total. Never patch the IDF unless the error log "
                    "contains a concrete severe model fault. Finish with a concise justification that "
                    "states evidence, action (or no action), and expected effect. If recent telemetry "
                    "contains a demonstration_constraint, satisfy it with an actual mutating tool call; "
                    "describing an action in text without calling the tool is invalid."
                ),
            },
            {
                "role": "user",
                "content": "Recent hourly telemetry:\n"
                + json.dumps(list(self.windows), separators=(",", ":")),
            },
        ]
        actions: list[dict[str, Any]] = []
        justification = "No supervisory change was needed."
        demo_action_required = any(
            "demonstration_constraint" in snapshot for snapshot in self.windows
        )
        for _ in range(MAX_TOOL_ROUNDS):
            has_mutating_action = any(
                action["tool"] in MUTATING_TOOLS for action in actions
            )
            response = client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice=(
                    "required"
                    if demo_action_required and not has_mutating_action
                    else "auto"
                ),
                temperature=0.1,
                max_completion_tokens=600,
            )
            message = response.choices[0].message
            if not message.tool_calls:
                justification = message.content or justification
                break
            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                name = call.function.name
                if name not in {schema["function"]["name"] for schema in TOOL_SCHEMAS}:
                    result: Any = {"error": f"Tool {name!r} is not allowed"}
                elif name in MUTATING_TOOLS and len(
                    [action for action in actions if action["tool"] in MUTATING_TOOLS]
                ) >= MAX_ACTIONS:
                    result = {"error": "Tier 2 action limit reached"}
                else:
                    parsed_args = json.loads(call.function.arguments or "{}")
                    args = parsed_args if isinstance(parsed_args, dict) else {}
                    args = {
                        key: value
                        for key, value in args.items()
                        if key in TOOL_PARAMETER_NAMES[name]
                    }
                    result = getattr(self.tools, name)(**args)
                    actions.append({"tool": name, "arguments": args, "result": result})
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
                )
        event = {
            "type": "reason_action",
            "simulation_time": self.state.snapshot()["simulation_time"],
            "model": self.settings.llm_model,
            "actions": actions,
            "justification": justification,
        }
        self.state.log_reason(event)
        return event
