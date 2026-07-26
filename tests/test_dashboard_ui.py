from pathlib import Path

import pytest

from ecoloop.cli import parser
from ecoloop.dashboard_ui import (
    DASHBOARD_TITLE,
    PRODUCT_NAME,
    TOTAL_POLICY_EPISODES,
    episode_exceeds_total,
    format_episode_progress,
    load_json_document,
    parse_episode_number,
    representative_block_index,
    representative_blocks,
    representative_position,
    representative_ticks,
)


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_uses_buildingdna_title_and_not_legacy_title() -> None:
    source = (ROOT / "dashboard.py").read_text(encoding="utf-8")

    assert DASHBOARD_TITLE == "BuildingDNA Control Room"
    assert PRODUCT_NAME == "BuildingDNA"
    assert "Eco-Loop control room" not in source
    assert 'st.title(DASHBOARD_TITLE)' in source
    assert "page_title=DASHBOARD_TITLE" in source


def test_episode_145_renders_against_180() -> None:
    progress = format_episode_progress(145)

    assert TOTAL_POLICY_EPISODES == 180
    assert progress == "Episode 145 / 180"
    assert not progress.endswith("/ 18")


@pytest.mark.parametrize(
    ("zone", "resolution", "modes"),
    (
        ("Core_ZN", "Daily", ("Balanced",)),
        ("Perimeter_ZN_3", "Weekly", ("Comfort Priority",)),
        ("Perimeter_ZN_4", "Monthly", ("Energy Saver", "Balanced")),
    ),
)
def test_dashboard_filters_do_not_change_episode_denominator(
    zone: str,
    resolution: str,
    modes: tuple[str, ...],
) -> None:
    assert zone and resolution and modes
    assert format_episode_progress(145) == "Episode 145 / 180"


@pytest.mark.parametrize("missing", (None, "", float("nan"), "not-a-number", 4.5))
def test_missing_or_invalid_episode_renders_safely(missing: object) -> None:
    assert parse_episode_number(missing) is None
    assert format_episode_progress(missing) == "Episode — / 180"


def test_corrupt_episode_above_total_is_not_hidden() -> None:
    assert episode_exceeds_total(181) is True
    assert format_episode_progress(181) == "Episode 181 / 180"


def test_internal_cli_name_remains_ecoloop() -> None:
    root_parser = parser()

    assert root_parser.prog == "ecoloop"
    assert "debate-preview" in root_parser.format_help()


def test_representative_timeline_removes_unsimulated_gaps() -> None:
    hours = [336, 337, 338, 2520, 2521, 4680, 4681]

    assert representative_blocks(hours) == [
        [336, 337, 338],
        [2520, 2521],
        [4680, 4681],
    ]
    assert representative_position(336, hours) == 0
    assert representative_position(2520, hours) == 3
    assert representative_position(4681, hours) == 6
    assert representative_block_index(2521, hours) == 1
    assert representative_ticks(hours) == (
        [0, 3, 5],
        ["Day 15", "Day 106", "Day 196"],
    )


def test_dashboard_replay_skips_unsimulated_hours() -> None:
    source = (ROOT / "dashboard.py").read_text(encoding="utf-8")

    assert 'RESULTS / mode / "summary.json"' in source
    assert 'RESULTS / mode / "telemetry.csv"' in source
    assert "select_slider(" in source
    assert "options=available_hours" in source
    assert "Sampled Period Replay" in source
    assert "Representative-period performance" in source
    assert "Annual performance" not in source
    assert 'load_proof("matched-12h/comparison.json")' in source
    assert "MATCHED EVALUATION" in source
    assert "Lines connect consecutive episodes within each simulated seasonal week" in source
    assert '"color": block_rows["mode"].map(MODE_COLORS)' in source
    assert '<span class="reason-day">Day {simulated_day}</span>' in source
    assert "with entry.expander" not in source
    assert "full-year-tier1" not in source


def test_json_loader_accepts_utf8_bom(tmp_path: Path) -> None:
    document = tmp_path / "powershell-output.json"
    document.write_bytes(b'\xef\xbb\xbf{"passed": true}')

    assert load_json_document(document) == {"passed": True}
