from __future__ import annotations

import json
from collections import deque
from typing import Any

from ecoloop.config import Settings
from ecoloop.debate import DebateEngine, DebateMode, optimization_priority
from ecoloop.decision import (
    StructuredDecision,
    action_label,
    compact_decision_context,
    fallback_decision,
    parse_structured_decision,
)
from ecoloop.response_quality import NON_ACTIONABLE_LABEL, truncate_text
from ecoloop.state import LiveState
from ecoloop.tools import ControlTools


DECISION_SYSTEM_PROMPT = """
You are BuildingDNA's Tier 2 building-management supervisor.
Make one concise operational decision from the supplied compact building context.
Never explain the JSON structure, enumerate telemetry fields, summarize the dataset,
or give generic conclusions. Never begin with "This is a JSON", "Here's a breakdown",
"The data contains", or "Without more context".
Use only measured values. Do not invent humidity, ventilation, weather, savings, or actions.
Tier 1 is the final safety authority and clamps every setpoint request.
Return exactly one strict JSON object matching the supplied schema and no other text.
Each visible field must be direct, actionable, and concise.
""".strip()

REPAIR_SYSTEM_PROMPT = """
Your previous response was invalid or non-actionable.
Return a corrected building-control decision as strict JSON only.
Do not explain JSON, schemas, fields, or datasets. Do not use markdown fences.
Do not repeat the invalid response. Use the compact context and required schema.
""".strip()

# Compatibility export used by the existing integrated LLM-to-actuator proof.
# Live structured decisions use the typed SupervisoryAction model instead.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "set_setpoint",
            "description": (
                "Queue a supervisory setpoint; the reflex layer clamps it for safety."
            ),
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
    }
]


class ReasonAgent:
    def __init__(self, settings: Settings, state: LiveState, tools: ControlTools) -> None:
        self.settings = settings
        self.state = state
        self.tools = tools
        self.windows: deque[dict[str, Any]] = deque(maxlen=12)
        self.previous_action: dict[str, Any] | None = None

    def observe(self, snapshot: dict[str, Any]) -> None:
        self.windows.append(snapshot)

    def run_once(self) -> dict[str, Any]:
        """Run one synchronous reasoning cycle; useful for startup checks and tests."""
        if not self.settings.ecoloop_reason_enabled:
            raise RuntimeError("Tier 2 is disabled by ECOLOOP_REASON_ENABLED")
        return self._reason()

    def _reason(self) -> dict[str, Any]:
        from openai import OpenAI

        client = OpenAI(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            timeout=self.settings.llm_timeout_seconds,
        )
        debate_mode = DebateMode(self.settings.ai_debate_mode)
        if debate_mode is not DebateMode.OFF:
            return self._reason_debate(client, debate_mode)
        return self._reason_structured(client)

    def _reason_debate(self, client: Any, debate_mode: DebateMode) -> dict[str, Any]:
        debate, actions = DebateEngine(self.settings, self.tools, client).run(
            list(self.windows),
            debate_mode,
        )
        applied_action = actions[0] if actions else None
        estimate = debate.estimated_energy_saving_percent
        recommended = action_label(
            debate.final_action.model_dump(mode="json")
            if debate.final_action is not None
            else None
        )
        event = {
            "type": "reason_debate",
            "event_type": "ai_debate",
            "simulation_time": debate.simulation_time,
            "model": debate.model_name,
            "debate_mode": debate_mode.value,
            "actions": actions,
            "justification": debate.consensus_summary,
            "debate": debate.model_dump(mode="json"),
            "optimization_priority": debate.optimization_priority.value,
            "diagnosis": debate.arbiter.recommendation,
            "recommended_action": recommended,
            "reason": debate.consensus_summary,
            "expected_impact": {
                "energy": (
                    "No model estimate claimed."
                    if estimate is None
                    else f"Model estimate: {estimate:.1f}% potential saving."
                ),
                "comfort": debate.estimated_comfort_impact,
            },
            "confidence": debate.confidence,
            "safety_status": (
                "deterministic_fallback"
                if debate.fallback_used
                else (
                    "queued_for_tier1_validation"
                    if applied_action
                    else "no_action_requested"
                )
            ),
            "applied_action": applied_action,
            "fallback_used": debate.fallback_used,
        }
        if applied_action:
            self.previous_action = applied_action
        self.state.log_reason(event)
        return event

    def _reason_structured(self, client: Any) -> dict[str, Any]:
        snapshot = self.windows[-1] if self.windows else self.state.snapshot()
        context = compact_decision_context(
            snapshot,
            self.settings,
            self.previous_action,
        )
        output_schema = StructuredDecision.model_json_schema()
        raw_response = ""
        parse_error: Exception | None = None
        decision: StructuredDecision | None = None

        for attempt in range(2):
            system_prompt = (
                DECISION_SYSTEM_PROMPT
                if attempt == 0
                else REPAIR_SYSTEM_PROMPT
            )
            user_payload: dict[str, Any] = {
                "task": "Choose one building-control action or explicitly choose no action.",
                "compact_context": context,
                "required_output_schema": output_schema,
            }
            if attempt == 1:
                user_payload["invalid_response_excerpt"] = truncate_text(
                    raw_response,
                    1200,
                )
                user_payload["validation_error"] = truncate_text(
                    parse_error,
                    240,
                )
            try:
                response = client.chat.completions.create(
                    model=self.settings.llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": json.dumps(user_payload, separators=(",", ":")),
                        },
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_completion_tokens=550,
                )
            except Exception as exc:
                parse_error = exc
                raw_response = ""
                continue
            raw_response = response.choices[0].message.content or ""
            try:
                decision = parse_structured_decision(raw_response)
                break
            except Exception as exc:
                parse_error = exc

        priority = optimization_priority(snapshot)
        fallback_used = decision is None
        if decision is None:
            decision = fallback_decision(priority)
        else:
            decision.optimization_priority = priority

        actions: list[dict[str, Any]] = []
        safety_status = (
            "deterministic_fallback" if fallback_used else "no_action_requested"
        )
        if decision.action is not None and not fallback_used:
            args = decision.action.arguments
            try:
                result = self.tools.set_setpoint(args.zone, args.value, args.kind)
                applied = {
                    "tool": decision.action.tool,
                    "arguments": args.model_dump(),
                    "result": result,
                    "source": "structured_tier2_decision",
                }
                actions.append(applied)
                self.previous_action = applied
                safety_status = "queued_for_tier1_validation"
            except Exception:
                decision = fallback_decision(priority, NON_ACTIONABLE_LABEL)
                fallback_used = True
                safety_status = "deterministic_fallback"

        applied_action = actions[0] if actions else None
        event = {
            "type": "reason_action",
            "event_type": "tier2_decision",
            "simulation_time": self.state.snapshot()["simulation_time"],
            "model": self.settings.llm_model,
            "actions": actions,
            "justification": decision.reason,
            "optimization_priority": decision.optimization_priority.value,
            "diagnosis": decision.diagnosis,
            "recommended_action": decision.recommended_action,
            "reason": decision.reason,
            "expected_impact": decision.expected_impact.model_dump(),
            "confidence": decision.confidence,
            "safety_status": safety_status,
            "applied_action": applied_action,
            "fallback_used": fallback_used,
            "raw_response": raw_response,
        }
        self.state.log_reason(event)
        return event
