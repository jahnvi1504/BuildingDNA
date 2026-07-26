from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ecoloop.config import Settings
from ecoloop.response_quality import (
    is_low_quality_output,
    strip_markdown_fences,
    truncate_text,
)
from ecoloop.state import ZONES
from ecoloop.tools import ControlTools


class DebateMode(str, Enum):
    OFF = "off"
    COMPACT = "compact"
    FULL = "full"


class OptimizationPriority(str, Enum):
    BALANCED = "balanced"
    COMFORT_FIRST = "comfort_first"
    ENERGY_FIRST = "energy_first"
    COST_FIRST = "cost_first"
    CARBON_FIRST = "carbon_first"
    SAFETY_FIRST = "safety_first"


class SetpointActionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone: str
    value: float
    kind: Literal["heating", "cooling"]


class SupervisoryAction(BaseModel):
    """Typed mirror of the existing set_setpoint tool-call format."""

    model_config = ConfigDict(extra="forbid")

    tool: Literal["set_setpoint"]
    arguments: SetpointActionArguments


class AgentPerspective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    recommendation: str
    proposed_action: SupervisoryAction | None = None
    expected_energy_saving_percent: float | None = None
    expected_comfort_impact: str
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CompactDebateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    optimization_priority: OptimizationPriority = OptimizationPriority.BALANCED
    energy_saver: AgentPerspective
    comfort_guardian: AgentPerspective
    arbiter: AgentPerspective
    final_action: SupervisoryAction | None = None
    consensus_summary: str
    disagreement_summary: str
    estimated_energy_saving_percent: float | None = None
    estimated_comfort_impact: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DebateResult(CompactDebateResponse):
    confidence: float = Field(ge=0.0, le=1.0)
    generated_at: datetime
    simulation_time: str
    model_name: str
    fallback_used: bool = False


def optimization_priority(snapshot: dict[str, Any]) -> OptimizationPriority:
    mode = str(snapshot.get("macro_policy", {}).get("mode", "")).casefold()
    if mode == "energy saver":
        return OptimizationPriority.ENERGY_FIRST
    if mode == "comfort priority":
        return OptimizationPriority.COMFORT_FIRST
    return OptimizationPriority.BALANCED


def safety_limits(settings: Settings, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "absolute_min_c": settings.absolute_min_c,
        "absolute_max_c": settings.absolute_max_c,
        "occupied_heating_min_c": settings.occupied_heating_min_c,
        "occupied_cooling_max_c": settings.occupied_cooling_max_c,
        "minimum_deadband_c": 1.0,
        "max_setpoint_drift_c": snapshot.get("macro_policy", {}).get(
            "max_setpoint_drift_c"
        ),
        "final_authority": "Deterministic ReflexController clamps every request.",
    }


def available_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Expose only measured state and label missing signals instead of inventing them."""
    keys = (
        "simulation_time",
        "zone_temperatures_c",
        "pmv",
        "occupied",
        "energy_kwh",
        "carbon_intensity_kg_per_kwh",
        "carbon_kg",
        "heating_setpoint_c",
        "cooling_setpoint_c",
    )
    available = {
        key: snapshot.get(key)
        for key in keys
        if key in snapshot and snapshot.get(key) is not None
    }
    unavailable = ["outdoor_weather", "relative_humidity", "ventilation_rate"]
    if snapshot.get("occupied") is None:
        unavailable.append("occupancy")
    return {
        "available": available,
        "unavailable": unavailable,
        "note": "Do not infer or fabricate unavailable measurements.",
    }


def _json_content(response: Any) -> dict[str, Any]:
    content = strip_markdown_fences(response.choices[0].message.content or "")
    if is_low_quality_output(content):
        raise ValueError("Debate response was a generic telemetry/schema explanation")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Debate response must be one JSON object")
    return parsed


def _schema_instruction(model: type[BaseModel]) -> str:
    return (
        "Return strict JSON only, with no markdown or hidden reasoning. "
        "All energy-saving percentages are estimates, not measured simulation results. "
        "Use null when no safe action or estimate is justified. JSON schema: "
        + json.dumps(model.model_json_schema(), separators=(",", ":"))
    )


class DebateEngine:
    def __init__(
        self,
        settings: Settings,
        tools: ControlTools,
        client: Any,
    ) -> None:
        self.settings = settings
        self.tools = tools
        self.client = client

    def run(
        self,
        snapshots: list[dict[str, Any]],
        mode: DebateMode,
        *,
        execute_action: bool = True,
    ) -> tuple[DebateResult, list[dict[str, Any]]]:
        snapshot = snapshots[-1] if snapshots else {}
        priority = optimization_priority(snapshot)
        context = {
            "current_building_state": available_state(snapshot),
            "optimization_priority": priority.value,
            "deterministic_safety_limits": safety_limits(self.settings, snapshot),
        }
        try:
            if mode is DebateMode.FULL:
                result = self._full(context, priority)
            else:
                result = self._compact(context, priority)
            actions = (
                self._execute_final_action(result.final_action)
                if execute_action
                else []
            )
            return result, actions
        except Exception as exc:
            return self._fallback(snapshot, priority, exc), []

    def _request(self, system: str, payload: dict[str, Any], schema: type[BaseModel]) -> Any:
        invalid = ""
        error = ""
        for attempt in range(2):
            repair = (
                ""
                if attempt == 0
                else (
                    "\nThe prior response was invalid. Repair it once. Do not explain the "
                    "schema or repeat the invalid prose."
                )
            )
            user_payload = payload
            if attempt == 1:
                user_payload = {
                    **payload,
                    "invalid_response_excerpt": truncate_text(invalid, 1200),
                    "validation_error": truncate_text(error, 240),
                }
            response = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": f"{system}{repair}\n{_schema_instruction(schema)}",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, separators=(",", ":")),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_completion_tokens=900,
            )
            invalid = response.choices[0].message.content or ""
            try:
                return schema.model_validate(_json_content(response))
            except Exception as exc:
                error = str(exc)
        raise ValueError(f"Debate JSON remained invalid after one repair: {error}")

    def _compact(
        self,
        context: dict[str, Any],
        priority: OptimizationPriority,
    ) -> DebateResult:
        response = self._request(
            (
                "Simulate a concise three-role building-control debate in one response. "
                "Energy Saver proposes an energy/peak focused action within the supplied bounds. "
                "Comfort Guardian reviews that proposal for measured PMV, occupancy, humidity, "
                "ventilation, and transition risks; explicitly note unavailable signals. "
                "BuildingDNA Arbiter balances both views using the optimization priority and "
                "selects at most one final action. Never explain the telemetry JSON, enumerate "
                "fields, or summarize the dataset. Summaries only; never reveal chain-of-thought."
            ),
            context,
            CompactDebateResponse,
        )
        if response.optimization_priority is not priority:
            response.optimization_priority = priority
        if response.arbiter.proposed_action != response.final_action:
            response.arbiter.proposed_action = response.final_action
        confidence = (
            response.confidence
            if response.confidence is not None
            else response.arbiter.confidence
        )
        return DebateResult(
            **{
                **response.model_dump(),
                "confidence": confidence,
            },
            generated_at=datetime.now(timezone.utc),
            simulation_time=str(
                context["current_building_state"]["available"].get("simulation_time", "")
            ),
            model_name=self.settings.llm_model,
            fallback_used=False,
        )

    def _full(
        self,
        context: dict[str, Any],
        priority: OptimizationPriority,
    ) -> DebateResult:
        energy = self._request(
            (
                "You are Energy Saver. Recommend at most one set_setpoint action to lower energy "
                "or peak demand. Use only measured inputs, remain inside the supplied hard bounds, "
                "state uncertainty, and provide concise summaries rather than internal reasoning. "
                "Never explain JSON, telemetry fields, or the dataset."
            ),
            context,
            AgentPerspective,
        )
        comfort = self._request(
            (
                "You are Comfort Guardian. Review the state and Energy Saver proposal. Prioritize "
                "PMV, occupancy, humidity, ventilation, and safe transitions. Explicitly identify "
                "unavailable signals and recommend accepting, modifying, or rejecting the proposal. "
                "Never explain JSON, telemetry fields, or the dataset."
            ),
            {**context, "energy_saver_proposal": energy.model_dump(mode="json")},
            AgentPerspective,
        )
        arbiter = self._request(
            (
                "You are BuildingDNA Arbiter. Balance both concise perspectives according to the "
                "optimization priority. Respect deterministic bounds and return at most one final "
                "set_setpoint action. Explain the compromise in one or two sentences only. Never "
                "explain JSON, telemetry fields, or the dataset."
            ),
            {
                **context,
                "energy_saver_proposal": energy.model_dump(mode="json"),
                "comfort_guardian_critique": comfort.model_dump(mode="json"),
            },
            AgentPerspective,
        )
        estimate = arbiter.expected_energy_saving_percent
        return DebateResult(
            optimization_priority=priority,
            energy_saver=energy,
            comfort_guardian=comfort,
            arbiter=arbiter,
            final_action=arbiter.proposed_action,
            consensus_summary=arbiter.recommendation,
            disagreement_summary="See the role risks and comfort assessment.",
            estimated_energy_saving_percent=estimate,
            estimated_comfort_impact=arbiter.expected_comfort_impact,
            confidence=arbiter.confidence,
            generated_at=datetime.now(timezone.utc),
            simulation_time=str(
                context["current_building_state"]["available"].get("simulation_time", "")
            ),
            model_name=self.settings.llm_model,
            fallback_used=False,
        )

    def _execute_final_action(
        self, action: SupervisoryAction | None
    ) -> list[dict[str, Any]]:
        if action is None:
            return []
        args = action.arguments
        if args.zone not in ZONES and args.zone != "ALL":
            raise ValueError(f"Arbiter selected unknown conditioned zone {args.zone!r}")
        result = self.tools.set_setpoint(args.zone, args.value, args.kind)
        return [
            {
                "tool": action.tool,
                "arguments": args.model_dump(),
                "result": result,
                "source": "debate_arbiter",
            }
        ]

    def _fallback(
        self,
        snapshot: dict[str, Any],
        priority: OptimizationPriority,
        error: Exception,
    ) -> DebateResult:
        concise_error = f"{type(error).__name__}: {str(error).splitlines()[0]}"[:240]
        perspective = AgentPerspective(
            role="BuildingDNA fallback",
            recommendation="Continue deterministic Tier 1 control with no supervisory change.",
            proposed_action=None,
            expected_energy_saving_percent=None,
            expected_comfort_impact="No additional impact; existing safety control remains active.",
            risks=[f"AI debate unavailable: {concise_error}"],
            confidence=1.0,
        )
        return DebateResult(
            optimization_priority=priority,
            energy_saver=perspective.model_copy(update={"role": "Energy Saver"}),
            comfort_guardian=perspective.model_copy(update={"role": "Comfort Guardian"}),
            arbiter=perspective.model_copy(update={"role": "BuildingDNA Arbiter"}),
            final_action=None,
            consensus_summary="AI debate unavailable; deterministic Tier 1 continued safely.",
            disagreement_summary="No AI recommendations were applied.",
            estimated_energy_saving_percent=None,
            estimated_comfort_impact="No supervisory change.",
            confidence=1.0,
            generated_at=datetime.now(timezone.utc),
            simulation_time=str(snapshot.get("simulation_time", "")),
            model_name=self.settings.llm_model,
            fallback_used=True,
        )
