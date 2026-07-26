from __future__ import annotations

import json
from pathlib import Path

from ecoloop.cli import parser
from ecoloop.config import Settings
from ecoloop.dashboard_ui import (
    EMPTY_DEBATE_MESSAGE,
    debate_replay_html,
)
from ecoloop.debate_replay import (
    DEBATE_REPLAY_PATH,
    build_demo_debate,
    load_debate_events,
    load_demo_debate,
    nearest_debate_event,
    select_debate_replay,
)


ROOT = Path(__file__).resolve().parents[1]


def snapshot(hour: int = 145) -> dict[str, object]:
    return {
        "simulation_time": f"day-{hour // 24 + 1:03d} {hour % 24:02d}:00",
        "hour": hour % 24,
        "occupied": True,
        "zone_temperatures_c": {"Core_ZN": 24.0},
        "pmv": {"Core_ZN": 0.1},
        "cooling_setpoint_c": 25.4,
        "heating_setpoint_c": 21.0,
        "macro_policy": {"mode": "Balanced", "max_setpoint_drift_c": 1.0},
    }


def test_no_event_uses_concise_empty_state(tmp_path: Path) -> None:
    assert load_debate_events(tmp_path / "missing.json") == []
    assert nearest_debate_event([], 145) is None
    assert EMPTY_DEBATE_MESSAGE == "No debate replay is available for this timestep."


def test_demo_event_renders_all_roles_source_and_safety(tmp_path: Path) -> None:
    event = load_demo_debate(
        snapshot(),
        145,
        Settings(_env_file=None),
        output_path=tmp_path / "debate.json",
    )

    rendered = debate_replay_html(event)

    assert rendered is not None
    assert "Energy Saver" in rendered
    assert "Comfort Guardian" in rendered
    assert "BuildingDNA Arbiter" in rendered
    assert "DEMO DATA" in rendered
    assert "Safety Result:" in rendered
    assert "Applied Action:" in rendered


def test_dashboard_has_no_debate_buttons_and_uses_automatic_demo() -> None:
    source = (ROOT / "dashboard.py").read_text(encoding="utf-8")

    assert "Generate Debate Replay" not in source
    assert "Load Demo Debate" not in source
    assert "st.spinner" not in source
    assert "select_debate_replay(" in source
    assert "EnergyPlusRunner" not in source


def test_in_memory_demo_does_not_write_outputs(tmp_path: Path) -> None:
    output = tmp_path / "debate.json"

    event = build_demo_debate(snapshot(), 145, Settings(_env_file=None))

    assert event["source"] == "demo"
    assert not output.exists()


def test_saved_replay_is_preferred_and_demo_fills_missing_state() -> None:
    settings = Settings(_env_file=None)
    saved = {"id": "saved", "replay_hour": 140, "source": "live_llm", "debate": {}}

    assert select_debate_replay([saved], 145, snapshot(), settings) is saved
    assert select_debate_replay([], 145, snapshot(), settings)["source"] == "demo"


def test_dashboard_and_cli_share_output_path() -> None:
    arguments = parser().parse_args(["debate-preview"])
    source = (ROOT / "dashboard.py").read_text(encoding="utf-8")

    assert arguments.output == DEBATE_REPLAY_PATH
    assert "load_debate_events(DEBATE_REPLAY_PATH)" in source


def test_nearest_replay_hour_is_selected() -> None:
    events = [
        {"replay_hour": 10, "debate": {}},
        {"replay_hour": 50, "debate": {}},
        {"replay_hour": 100, "debate": {}},
    ]

    assert nearest_debate_event(events, 48)["replay_hour"] == 50


def test_latest_event_wins_when_replay_hours_match() -> None:
    events = [
        {"id": "demo", "replay_hour": 48, "debate": {}},
        {"id": "generated", "replay_hour": 48, "debate": {}},
    ]

    assert nearest_debate_event(events, 48)["id"] == "generated"


def test_malformed_debate_data_does_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "debate.json"
    path.write_text("{bad json", encoding="utf-8")

    assert load_debate_events(path) == []
    assert debate_replay_html({"debate": {"energy_saver": "invalid"}}) is None


def test_generated_source_labels_live_then_saved(tmp_path: Path) -> None:
    event = load_demo_debate(
        snapshot(),
        145,
        Settings(_env_file=None),
        output_path=tmp_path / "debate.json",
    )
    event["source"] = "live_llm"

    assert "LIVE LLM DEBATE" in (debate_replay_html(event, live_event_id=event["id"]) or "")
    assert "SAVED REPLAY" in (debate_replay_html(event) or "")


def test_rendered_llm_text_is_escaped(tmp_path: Path) -> None:
    event = load_demo_debate(
        snapshot(),
        145,
        Settings(_env_file=None),
        output_path=tmp_path / "debate.json",
    )
    event["debate"]["energy_saver"]["recommendation"] = "<script>alert(1)</script>"

    rendered = debate_replay_html(event)

    assert rendered is not None
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_new_store_and_legacy_event_remain_readable(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "type": "debate_preview",
                "debate": {
                    "simulation_time": "day-002 03:00",
                    "fallback_used": True,
                },
            }
        ),
        encoding="utf-8",
    )

    events = load_debate_events(path)

    assert events[0]["replay_hour"] == 27
    assert events[0]["safety_result"]["status"] == "FALLBACK"
