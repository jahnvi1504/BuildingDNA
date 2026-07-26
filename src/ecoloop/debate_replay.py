from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ecoloop.config import PROJECT_ROOT, Settings
from ecoloop.debate import (
    AgentPerspective,
    DebateEngine,
    DebateMode,
    DebateResult,
    OptimizationPriority,
    SupervisoryAction,
)
from ecoloop.reflex import ReflexController
from ecoloop.state import LiveState, SetpointRequest, ZONES
from ecoloop.tools import ControlTools


DEBATE_REPLAY_PATH = PROJECT_ROOT / "outputs" / "debate-demo" / "debate.json"
DEFAULT_DEBATE_SUMMARY_PATH = (
    PROJECT_ROOT / "outputs" / "matched-12h" / "agent" / "summary.json"
)
MAX_SAVED_DEBATES = 200


class DebateReplayError(RuntimeError):
    pass


def simulation_hour(value: object) -> int | None:
    text = str(value or "")
    if not text.startswith("day-"):
        return None
    try:
        day_text, clock = text.split()
        day = int(day_text.removeprefix("day-"))
        hour, minute = (int(part) for part in clock.split(":"))
    except (TypeError, ValueError):
        return None
    return max(0, (day - 1) * 24 + hour + minute // 60)


def replay_snapshot(
    row: Mapping[str, Any],
    replay_hour: int,
    macro_policy: Mapping[str, Any],
) -> dict[str, Any]:
    temperatures = {
        zone: float(row[f"temp_{zone}"])
        for zone in ZONES
        if row.get(f"temp_{zone}") is not None
    }
    pmv = {
        zone: float(row[f"pmv_{zone}"])
        for zone in ZONES
        if row.get(f"pmv_{zone}") is not None
    }
    return {
        "simulation_time": (
            f"day-{replay_hour // 24 + 1:03d} {replay_hour % 24:02d}:00"
        ),
        "day_of_year": replay_hour // 24 + 1,
        "hour": replay_hour % 24,
        "minute": 0,
        "occupied": row.get("occupied"),
        "zone_temperatures_c": temperatures,
        "pmv": pmv,
        "energy_kwh": _optional_float(row.get("energy_kwh")),
        "carbon_intensity_kg_per_kwh": _optional_float(
            row.get("carbon_intensity_kg_per_kwh")
        ),
        "carbon_kg": _optional_float(row.get("carbon_kg")),
        "heating_setpoint_c": _optional_float(row.get("heating_setpoint_c")),
        "cooling_setpoint_c": _optional_float(row.get("cooling_setpoint_c")),
        "macro_policy": dict(macro_policy),
    }


def _optional_float(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def load_debate_events(path: Path = DEBATE_REPLAY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        candidates = payload["events"]
    elif isinstance(payload, dict) and isinstance(payload.get("debate"), dict):
        candidates = [_upgrade_legacy_event(payload)]
    else:
        return []
    return [
        dict(event)
        for event in candidates
        if isinstance(event, dict) and isinstance(event.get("debate"), dict)
    ]


def nearest_debate_event(
    events: list[dict[str, Any]],
    replay_hour: int,
) -> dict[str, Any] | None:
    valid = [
        event
        for event in events
        if isinstance(event.get("replay_hour"), int)
    ]
    if not valid:
        return None
    return min(
        reversed(valid),
        key=lambda event: (
            abs(int(event["replay_hour"]) - replay_hour),
            -int(event["replay_hour"]),
        ),
    )


def select_debate_replay(
    events: list[dict[str, Any]],
    replay_hour: int,
    snapshot: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Prefer the nearest saved event, otherwise return an in-memory demo."""
    return nearest_debate_event(events, replay_hour) or build_demo_debate(
        snapshot,
        replay_hour,
        settings,
    )


def persist_debate_event(
    event: dict[str, Any],
    path: Path = DEBATE_REPLAY_PATH,
) -> dict[str, Any]:
    events = load_debate_events(path)
    events = [
        existing
        for existing in events
        if not (
            existing.get("replay_hour") == event.get("replay_hour")
            and existing.get("source") == event.get("source")
        )
    ]
    events.append(event)
    events = sorted(events, key=lambda item: int(item.get("replay_hour", 0)))[
        -MAX_SAVED_DEBATES:
    ]
    payload = {"schema_version": 2, "events": events}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)
    return event


def generate_debate_replay(
    snapshot: dict[str, Any],
    replay_hour: int,
    settings: Settings,
    *,
    mode: DebateMode = DebateMode.COMPACT,
    output_path: Path = DEBATE_REPLAY_PATH,
    source_summary: str | None = None,
) -> dict[str, Any]:
    try:
        from openai import OpenAI

        state = LiveState()
        tools = ControlTools(
            state=state,
            idf_path=settings.resolved(settings.ecoloop_idf),
            idd_path=settings.resolved(settings.energyplus_home) / "Energy+.idd",
        )
        client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        result, _ = DebateEngine(settings, tools, client).run(
            [snapshot],
            mode,
            execute_action=False,
        )
    except Exception as exc:
        raise DebateReplayError(f"Unable to contact the configured local model: {exc}") from exc

    event = _event_from_result(
        result,
        snapshot,
        replay_hour,
        settings,
        source="live_llm",
        source_summary=source_summary,
    )
    return persist_debate_event(event, output_path)


def load_demo_debate(
    snapshot: dict[str, Any],
    replay_hour: int,
    settings: Settings,
    *,
    output_path: Path = DEBATE_REPLAY_PATH,
) -> dict[str, Any]:
    return persist_debate_event(
        build_demo_debate(snapshot, replay_hour, settings),
        output_path,
    )


def build_demo_debate(
    snapshot: dict[str, Any],
    replay_hour: int,
    settings: Settings,
) -> dict[str, Any]:
    """Build an in-memory deterministic replay without touching simulation outputs."""
    cooling = _optional_float(snapshot.get("cooling_setpoint_c")) or 25.4
    requested = round(min(cooling + 0.3, settings.absolute_max_c), 1)
    action = SupervisoryAction.model_validate(
        {
            "tool": "set_setpoint",
            "arguments": {
                "zone": "ALL",
                "value": requested,
                "kind": "cooling",
            },
        }
    )
    energy = AgentPerspective(
        role="Energy Saver",
        recommendation=(
            f"Test a {requested:.1f}°C cooling setpoint to reduce compressor demand."
        ),
        proposed_action=action,
        expected_energy_saving_percent=3.0,
        expected_comfort_impact="Slightly warmer zones; requires safety validation.",
        risks=["Warm perimeter zones may narrow the comfort margin."],
        confidence=0.72,
    )
    comfort = AgentPerspective(
        role="Comfort Guardian",
        recommendation="Modify the proposal if PMV or occupied limits are exceeded.",
        proposed_action=None,
        expected_energy_saving_percent=None,
        expected_comfort_impact="Protect the configured occupied comfort envelope.",
        risks=["Demo data does not add humidity or ventilation measurements."],
        confidence=0.88,
    )
    arbiter = AgentPerspective(
        role="BuildingDNA Arbiter",
        recommendation="Accept only the Tier 1 validated version of the proposed setpoint.",
        proposed_action=action,
        expected_energy_saving_percent=2.0,
        expected_comfort_impact="Comfort maintained by deterministic clamping.",
        risks=["Energy impact is a demo estimate, not a measured result."],
        confidence=0.8,
    )
    result = DebateResult(
        optimization_priority=OptimizationPriority.BALANCED,
        energy_saver=energy,
        comfort_guardian=comfort,
        arbiter=arbiter,
        final_action=action,
        consensus_summary=(
            "Use the conservative energy-saving proposal only after Tier 1 validation."
        ),
        disagreement_summary=(
            "Comfort Guardian requires the deterministic occupied-limit clamp."
        ),
        estimated_energy_saving_percent=2.0,
        estimated_comfort_impact="Comfort maintained by deterministic clamping.",
        confidence=0.8,
        generated_at=datetime.now(timezone.utc),
        simulation_time=str(snapshot.get("simulation_time", "")),
        model_name="deterministic-demo",
        fallback_used=False,
    )
    return _event_from_result(
        result,
        snapshot,
        replay_hour,
        settings,
        source="demo",
    )


def _event_from_result(
    result: DebateResult,
    snapshot: dict[str, Any],
    replay_hour: int,
    settings: Settings,
    *,
    source: str,
    source_summary: str | None = None,
) -> dict[str, Any]:
    safety = _preview_safety(result, snapshot, settings)
    return {
        "id": uuid4().hex,
        "type": "debate_replay",
        "source": source,
        "replay_hour": int(replay_hour),
        "simulation_time": result.simulation_time,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "replay_only": True,
        "action_applied": False,
        "source_summary": source_summary,
        "debate": result.model_dump(mode="json"),
        "safety_result": safety,
        "applied_action": safety.get("validated_action"),
    }


def _preview_safety(
    result: DebateResult,
    snapshot: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    if result.fallback_used:
        return {
            "status": "FALLBACK",
            "reason": "Local-model debate failed; deterministic control remains active.",
            "validated_action": None,
        }
    if result.final_action is None:
        return {
            "status": "REJECTED",
            "reason": "The Arbiter selected no supervisory action.",
            "validated_action": None,
        }

    args = result.final_action.arguments
    state = LiveState()
    try:
        state.queue_setpoint(
            SetpointRequest(
                zone=args.zone,
                value_c=args.value,
                kind=args.kind,
                source="debate_replay",
            )
        )
    except ValueError as exc:
        return {
            "status": "REJECTED",
            "reason": str(exc),
            "validated_action": None,
        }

    controller = ReflexController(settings, state)
    policy = snapshot.get("macro_policy", {})
    max_drift = _optional_float(policy.get("max_setpoint_drift_c"))
    decision = controller.step(
        dict(snapshot.get("zone_temperatures_c", {})),
        occupied=bool(snapshot.get("occupied")),
        max_drift_c=max_drift,
    )
    validated_value = (
        decision.cooling_c if args.kind == "cooling" else decision.heating_c
    )
    status = "APPROVED" if abs(validated_value - args.value) < 1e-9 else "MODIFIED"
    return {
        "status": status,
        "reason": decision.reason,
        "requested_action": result.final_action.model_dump(mode="json"),
        "validated_action": {
            "tool": "set_setpoint",
            "arguments": {
                "zone": args.zone,
                "value": validated_value,
                "kind": args.kind,
            },
            "replay_only": True,
        },
    }


def _upgrade_legacy_event(payload: dict[str, Any]) -> dict[str, Any]:
    debate = payload.get("debate", {})
    hour = simulation_hour(debate.get("simulation_time")) or 0
    fallback = bool(debate.get("fallback_used"))
    final_action = debate.get("final_action")
    status = "FALLBACK" if fallback else ("APPROVED" if final_action else "REJECTED")
    return {
        "id": "legacy-debate-preview",
        "type": "debate_replay",
        "source": "live_llm",
        "replay_hour": hour,
        "simulation_time": debate.get("simulation_time", ""),
        "created_at": debate.get("generated_at", ""),
        "replay_only": True,
        "action_applied": False,
        "source_summary": payload.get("source_summary"),
        "debate": debate,
        "safety_result": {
            "status": status,
            "reason": "Legacy replay; detailed safety preview was not recorded.",
            "validated_action": final_action,
        },
        "applied_action": final_action,
    }
