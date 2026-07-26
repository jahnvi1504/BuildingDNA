from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from ecoloop.config import Settings
from ecoloop.debate import (
    OptimizationPriority,
    SupervisoryAction,
    optimization_priority,
    safety_limits,
)
from ecoloop.response_quality import (
    NON_ACTIONABLE_LABEL,
    escaped_truncated,
    is_low_quality_output,
    strip_markdown_fences,
    truncate_text,
)


class ExpectedImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    energy: str = Field(max_length=160)
    comfort: str = Field(max_length=160)


class StructuredDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis: str = Field(max_length=240)
    recommended_action: str = Field(max_length=240)
    reason: str = Field(max_length=300)
    optimization_priority: OptimizationPriority
    confidence: float = Field(ge=0.0, le=1.0)
    expected_impact: ExpectedImpact
    action: SupervisoryAction | None = None


def parse_structured_decision(content: str) -> StructuredDecision:
    cleaned = strip_markdown_fences(content)
    if is_low_quality_output(cleaned):
        raise ValueError("LLM response was a generic telemetry/schema explanation")
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Tier 2 response must be one JSON object")
    decision = StructuredDecision.model_validate(parsed)
    visible = " ".join(
        (
            decision.diagnosis,
            decision.recommended_action,
            decision.reason,
            decision.expected_impact.energy,
            decision.expected_impact.comfort,
        )
    )
    if is_low_quality_output(visible):
        raise ValueError("Structured fields contained a generic telemetry/schema explanation")
    return decision


def compact_decision_context(
    snapshot: dict[str, Any],
    settings: Settings,
    previous_action: dict[str, Any] | None,
) -> dict[str, Any]:
    policy = snapshot.get("macro_policy", {})
    context = {
        "simulation_time": snapshot.get("simulation_time", ""),
        "zone_temperatures_c": snapshot.get("zone_temperatures_c", {}),
        "pmv": snapshot.get("pmv", {}),
        "occupancy": snapshot.get("occupied"),
        "energy_kwh": snapshot.get("energy_kwh"),
        "carbon_intensity_kg_per_kwh": snapshot.get(
            "carbon_intensity_kg_per_kwh"
        ),
        "active_setpoints_c": {
            "heating": snapshot.get("heating_setpoint_c"),
            "cooling": snapshot.get("cooling_setpoint_c"),
        },
        "macro_policy": {
            key: policy.get(key)
            for key in (
                "mode",
                "comfort_band",
                "max_setpoint_drift_c",
                "description",
            )
            if key in policy
        },
        "optimization_priority": optimization_priority(snapshot).value,
        "comfort_limits": safety_limits(settings, snapshot),
        "previous_action": previous_action,
    }
    if "demonstration_constraint" in snapshot:
        context["demonstration_constraint"] = snapshot["demonstration_constraint"]
    return context


def fallback_decision(
    priority: OptimizationPriority,
    reason: str = NON_ACTIONABLE_LABEL,
) -> StructuredDecision:
    return StructuredDecision(
        diagnosis=NON_ACTIONABLE_LABEL,
        recommended_action="Continue deterministic Tier 1 control.",
        reason=truncate_text(reason, 300),
        optimization_priority=priority,
        confidence=1.0,
        expected_impact=ExpectedImpact(
            energy="No AI-attributed change.",
            comfort="Existing deterministic safety envelope remains active.",
        ),
        action=None,
    )


def action_label(action: object) -> str:
    if not isinstance(action, Mapping):
        return "No supervisory action."
    tool = str(action.get("tool", "action"))
    arguments = action.get("arguments", {})
    if isinstance(arguments, Mapping) and tool == "set_setpoint":
        return (
            f"Set {arguments.get('zone', 'zone')} {arguments.get('kind', 'setpoint')} "
            f"to {arguments.get('value', '—')}°C."
        )
    return truncate_text(tool.replace("_", " ").title(), 240)


def normalize_reasoning_record(record: Mapping[str, Any]) -> dict[str, Any]:
    raw = str(record.get("raw_response") or record.get("justification") or "")
    generic = bool(raw and is_low_quality_output(raw))
    actions = record.get("actions")
    first_action = (
        actions[0]
        if isinstance(actions, list) and actions and isinstance(actions[0], Mapping)
        else None
    )
    applied = record.get("applied_action") or first_action
    fallback = bool(record.get("fallback_used")) or generic

    if record.get("diagnosis"):
        diagnosis = str(record["diagnosis"])
    elif generic:
        diagnosis = NON_ACTIONABLE_LABEL
    else:
        diagnosis = raw or "Legacy reasoning event."

    recommended = str(
        record.get("recommended_action")
        or action_label(applied)
    )
    if generic:
        reason = NON_ACTIONABLE_LABEL
    elif not record.get("reason") and raw:
        reason = "Legacy entry retained; open Technical details for the original response."
    else:
        reason = str(record.get("reason") or raw or "No concise reason recorded.")

    impact = record.get("expected_impact")
    if not isinstance(impact, Mapping):
        impact = {
            "energy": "Not recorded in this legacy event.",
            "comfort": "Not recorded in this legacy event.",
        }
    safety = str(
        record.get("safety_status")
        or (
            "deterministic_fallback"
            if fallback
            else "legacy_event; Tier 1 remained final authority"
        )
    )
    return {
        "simulation_time": str(record.get("simulation_time", "")),
        "event_type": str(record.get("event_type") or record.get("type") or "legacy"),
        "optimization_priority": str(
            record.get("optimization_priority") or "balanced"
        ),
        "diagnosis": truncate_text(diagnosis, 240),
        "recommended_action": truncate_text(recommended, 240),
        "reason": truncate_text(reason, 300),
        "expected_impact": {
            "energy": truncate_text(impact.get("energy", "Not recorded."), 160),
            "comfort": truncate_text(impact.get("comfort", "Not recorded."), 160),
        },
        "confidence": record.get("confidence"),
        "safety_status": truncate_text(safety, 160),
        "applied_action": applied,
        "fallback_used": fallback,
        "raw_response": raw,
        "raw_record": dict(record),
    }


def reasoning_card_html(record: Mapping[str, Any], macro_policy: str) -> str:
    normalized = normalize_reasoning_record(record)
    confidence = normalized["confidence"]
    confidence_text = "Not recorded" if confidence is None else f"{float(confidence):.0%}"
    impact = normalized["expected_impact"]
    fallback = " · fallback" if normalized["fallback_used"] else ""
    return (
        '<div class="reason">'
        f'<small>{escaped_truncated(normalized["simulation_time"], 80)}'
        f'<span class="reason-mode">{escaped_truncated(macro_policy, 80)}</span></small>'
        f'<div><strong>Diagnosis:</strong> {escaped_truncated(normalized["diagnosis"], 100)}</div>'
        '<div><strong>Recommended/applied:</strong> '
        f'{escaped_truncated(normalized["recommended_action"], 100)}</div>'
        f'<div><strong>Reason:</strong> {escaped_truncated(normalized["reason"], 140)}</div>'
        '<div><strong>Expected impact:</strong> Energy — '
        f'{escaped_truncated(impact["energy"], 60)}; Comfort — '
        f'{escaped_truncated(impact["comfort"], 60)}</div>'
        f'<div><strong>Confidence:</strong> {escaped_truncated(confidence_text, 40)}</div>'
        '<div><strong>Safety:</strong> '
        f'{escaped_truncated(normalized["safety_status"], 60)}'
        f'{escaped_truncated(fallback, 20)}</div></div>'
    )
