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
]


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
        if not self.settings.ecoloop_reason_enabled or not self.settings.groq_api_key:
            return False
        with self._lock:
            if self._running:
                return False
            self._running = True
        threading.Thread(target=self._run, daemon=True, name="ecoloop-reason").start()
        return True

    def _run(self) -> None:
        try:
            from groq import Groq

            client = Groq(api_key=self.settings.groq_api_key)
            summary = list(self.windows)
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "You supervise an EnergyPlus office. Minimize electricity and carbon while "
                        "keeping occupied-zone PMV between -0.5 and +0.5. Tier 1 enforces hard safety. "
                        "Use tools for telemetry and at most two setpoint actions. Return a concise "
                        "plain-language justification describing evidence, action, and expected effect."
                    ),
                },
                {
                    "role": "user",
                    "content": "Aggregated recent telemetry:\n" + json.dumps(summary, separators=(",", ":")),
                },
            ]
            response = client.chat.completions.create(
                model=self.settings.groq_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.1,
                max_completion_tokens=600,
            )
            message = response.choices[0].message
            actions: list[dict[str, Any]] = []
            if message.tool_calls:
                messages.append(message.model_dump(exclude_none=True))
                for call in message.tool_calls:
                    args = json.loads(call.function.arguments or "{}")
                    result = getattr(self.tools, call.function.name)(**args)
                    actions.append({"tool": call.function.name, "arguments": args, "result": result})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(result),
                        }
                    )
                final = client.chat.completions.create(
                    model=self.settings.groq_model,
                    messages=messages,
                    temperature=0.1,
                    max_completion_tokens=180,
                )
                justification = final.choices[0].message.content or "Action issued from telemetry."
            else:
                justification = message.content or "No supervisory change was needed."
            self.state.log_reason(
                {
                    "type": "reason_action",
                    "simulation_time": self.state.snapshot()["simulation_time"],
                    "model": self.settings.groq_model,
                    "actions": actions,
                    "justification": justification,
                }
            )
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

