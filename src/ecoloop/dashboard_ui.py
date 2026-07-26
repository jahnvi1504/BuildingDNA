from __future__ import annotations

import math
import json
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Any

from ecoloop.decision import action_label
from ecoloop.response_quality import escaped_truncated


DASHBOARD_TITLE = "BuildingDNA Control Room"
PRODUCT_NAME = "BuildingDNA"
TOTAL_POLICY_EPISODES = 180
EMPTY_DEBATE_MESSAGE = "No debate replay is available for this timestep."


def load_json_document(path: Path) -> dict[str, Any]:
    """Load JSON written by either Python or PowerShell, which may include a BOM."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def representative_blocks(hours: list[int]) -> list[list[int]]:
    """Split sampled annual hours wherever the simulation has a real time gap."""
    ordered = sorted({int(hour) for hour in hours})
    blocks: list[list[int]] = []
    for hour in ordered:
        if not blocks or hour - blocks[-1][-1] > 1:
            blocks.append([hour])
        else:
            blocks[-1].append(hour)
    return blocks


def representative_position(hour: float, hours: list[int]) -> int:
    """Map an annual simulation hour onto the nearest compact timeline position."""
    ordered = sorted({int(item) for item in hours})
    if not ordered:
        return 0
    insertion = bisect_left(ordered, int(hour))
    if insertion == 0:
        return 0
    if insertion >= len(ordered):
        return len(ordered) - 1
    before = ordered[insertion - 1]
    after = ordered[insertion]
    return insertion - 1 if abs(hour - before) <= abs(after - hour) else insertion


def representative_block_index(hour: float, hours: list[int]) -> int:
    blocks = representative_blocks(hours)
    if not blocks:
        return 0
    starts = [block[0] for block in blocks]
    return max(0, min(len(blocks) - 1, bisect_right(starts, int(hour)) - 1))


def representative_ticks(hours: list[int]) -> tuple[list[int], list[str]]:
    blocks = representative_blocks(hours)
    ordered = sorted({int(hour) for hour in hours})
    positions = [ordered.index(block[0]) for block in blocks]
    labels = [f"Day {block[0] // 24 + 1}" for block in blocks]
    return positions, labels


def parse_episode_number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    return int(numeric)


def format_episode_progress(
    current_episode: int | None,
    total_episodes: int = TOTAL_POLICY_EPISODES,
) -> str:
    if total_episodes <= 0:
        raise ValueError("total_episodes must be positive")
    current = parse_episode_number(current_episode)
    current_text = "—" if current is None else str(current)
    return f"Episode {current_text} / {int(total_episodes)}"


def episode_exceeds_total(
    current_episode: int | None,
    total_episodes: int = TOTAL_POLICY_EPISODES,
) -> bool:
    current = parse_episode_number(current_episode)
    return current is not None and current > total_episodes


def debate_source_label(
    event: dict[str, Any],
    live_event_id: str | None = None,
) -> str:
    if event.get("source") == "verified_proof":
        return "VERIFIED ACTION REPLAY"
    if event.get("source") == "demo":
        return "DEMO DATA"
    if live_event_id and event.get("id") == live_event_id:
        return "LIVE LLM DEBATE"
    return "SAVED REPLAY"


def debate_replay_html(
    event: dict[str, Any],
    *,
    live_event_id: str | None = None,
) -> str | None:
    debate = event.get("debate")
    if not isinstance(debate, dict):
        return None
    energy = debate.get("energy_saver")
    comfort = debate.get("comfort_guardian")
    arbiter = debate.get("arbiter")
    if not all(isinstance(item, dict) for item in (energy, comfort, arbiter)):
        return None

    estimate = energy.get("expected_energy_saving_percent")
    try:
        energy_impact = f"Estimated {float(estimate):.1f}% potential saving"
    except (TypeError, ValueError):
        energy_impact = "No estimate claimed"
    comfort_risks = comfort.get("risks")
    comfort_concern = (
        str(comfort_risks[0])
        if isinstance(comfort_risks, list) and comfort_risks
        else str(comfort.get("expected_comfort_impact", "No concern stated"))
    )
    final_action = event.get("applied_action") or debate.get("final_action")
    applied = action_label(final_action)
    if event.get("replay_only"):
        applied = f"Replay only — {applied}"
    safety = event.get("safety_result")
    safety_status = (
        str(safety.get("status", "FALLBACK"))
        if isinstance(safety, dict)
        else "FALLBACK"
    )
    safety_evidence = (
        str(safety.get("evidence", ""))
        if isinstance(safety, dict)
        else ""
    )
    source = debate_source_label(event, live_event_id)

    def confidence(item: dict[str, Any]) -> str:
        if event.get("source") == "verified_proof":
            return "Evidence-backed"
        try:
            return f"{float(item.get('confidence')):.0%}"
        except (TypeError, ValueError):
            return "Not recorded"

    def confidence_width(item: dict[str, Any]) -> int:
        try:
            return max(0, min(100, round(float(item.get("confidence")) * 100)))
        except (TypeError, ValueError):
            return 0

    verification_html = (
        f'<strong>Verification:</strong> {escaped_truncated(safety_evidence, 120)}<br>'
        if safety_evidence
        else ""
    )
    return (
        '<div class="debate-stage">'
        f'<div class="debate-source"><span class="status-dot"></span>{escaped_truncated(source, 40)}</div>'
        '<div class="debate-grid">'
        '<div class="debate-card"><div class="ai-avatar">ES</div>'
        '<div class="debate-role">Energy Saver</div>'
        f'<div class="debate-copy">{escaped_truncated(energy.get("recommendation"), 240)}</div>'
        f'<div class="reason-bullet">{escaped_truncated(energy_impact, 120)}</div>'
        f'<div class="debate-meta">Confidence · {escaped_truncated(confidence(energy), 30)}</div>'
        '<div class="confidence-track">'
        f'<div class="confidence-fill" style="width:{confidence_width(energy)}%"></div></div></div>'
        '<div class="debate-card"><div class="ai-avatar">CG</div>'
        '<div class="debate-role">Comfort Guardian</div>'
        f'<div class="debate-copy">{escaped_truncated(comfort.get("recommendation"), 240)}</div>'
        f'<div class="reason-bullet">{escaped_truncated(comfort_concern, 150)}</div>'
        f'<div class="debate-meta">Confidence · {escaped_truncated(confidence(comfort), 30)}</div>'
        '<div class="confidence-track">'
        f'<div class="confidence-fill" style="width:{confidence_width(comfort)}%"></div></div></div>'
        '<div class="debate-card"><div class="ai-avatar">BD</div>'
        '<div class="debate-role">BuildingDNA Arbiter</div>'
        f'<div class="debate-copy">Final action: {escaped_truncated(action_label(debate.get("final_action")), 180)}</div>'
        f'<div class="reason-bullet">{escaped_truncated(debate.get("consensus_summary"), 190)}</div>'
        f'<div class="debate-meta">Confidence · {escaped_truncated(confidence(arbiter), 30)}</div>'
        '<div class="confidence-track">'
        f'<div class="confidence-fill" style="width:{confidence_width(arbiter)}%"></div></div></div>'
        '</div>'
        '<div class="decision-flow">'
        '<div class="flow-node">Energy Saver</div>'
        '<div class="flow-node">Comfort Guardian</div>'
        '<div class="flow-node">BuildingDNA Decision</div>'
        '<div class="flow-node">Verified Action</div>'
        '<div class="flow-node">EnergyPlus Callback</div>'
        '</div>'
        '<div class="debate-final">'
        '<div class="verify-check">✓</div><div class="verify-copy">'
        f'<strong>Verification completed · Safety Result: {escaped_truncated(safety_status, 40)}</strong><br>'
        f"{verification_html}"
        f'Applied Action: {escaped_truncated(applied, 240)}</div>'
        '</div></div>'
    )
