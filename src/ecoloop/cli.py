from __future__ import annotations

import argparse
import json
from pathlib import Path

from ecoloop.config import PROJECT_ROOT, settings
from ecoloop.debate import DebateMode
from ecoloop.debate_replay import (
    DEBATE_REPLAY_PATH,
    DEFAULT_DEBATE_SUMMARY_PATH,
    generate_debate_replay,
    simulation_hour,
)
from ecoloop.policy import build_policy_log
from ecoloop.reason import ReasonAgent
from ecoloop.simulation import EnergyPlusRunner
from ecoloop.state import LiveState
from ecoloop.tools import ControlTools


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="ecoloop")
    commands = root.add_subparsers(dest="command", required=True)
    simulate = commands.add_parser("simulate", help="Run live EnergyPlus control")
    simulate.add_argument("--mode", choices=("baseline", "agent"), required=True)
    simulate.add_argument("--output", type=Path)
    commands.add_parser("mcp", help="Run MCP server over stdio")
    commands.add_parser("reason-smoke", help="Make one safe Tier 2 tool-calling request")
    debate = commands.add_parser(
        "debate-preview",
        help="Generate a replay-only AI debate from saved telemetry",
    )
    debate.add_argument("--mode", choices=("compact", "full"), default="compact")
    debate.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_DEBATE_SUMMARY_PATH,
    )
    debate.add_argument(
        "--output",
        type=Path,
        default=DEBATE_REPLAY_PATH,
    )
    policy = commands.add_parser(
        "policy-evaluate", help="Score saved runs and write the macro-policy log"
    )
    policy.add_argument("--episode-hours", type=int, default=48)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "mcp":
        from ecoloop.mcp_server import main as run_mcp

        run_mcp()
        return 0
    if args.command == "reason-smoke":
        state = LiveState()
        state.update(
            simulation_time="smoke-test 14:00",
            hour=14,
            zone_temperatures_c={"Core_ZN": 24.0},
            pmv={"Core_ZN": 0.0},
            energy_kwh=100.0,
            carbon_intensity_kg_per_kwh=0.72,
        )
        tools = ControlTools(
            state=state,
            idf_path=settings.resolved(settings.ecoloop_idf),
            idd_path=settings.resolved(settings.energyplus_home) / "Energy+.idd",
        )
        agent = ReasonAgent(settings, state, tools)
        agent.observe(state.snapshot())
        event = agent.run_once()
        print(json.dumps({**event, "api_key": "redacted"}, indent=2))
        return 0
    if args.command == "debate-preview":
        saved = json.loads(args.summary.read_text(encoding="utf-8"))
        snapshot = {
            **saved,
            "macro_policy": {
                "mode": "Balanced",
                "max_setpoint_drift_c": 1.0,
            },
        }
        try:
            source_summary = args.summary.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            source_summary = str(args.summary)
        event = generate_debate_replay(
            snapshot,
            simulation_hour(snapshot.get("simulation_time")) or 0,
            settings,
            mode=DebateMode(args.mode),
            output_path=args.output,
            source_summary=source_summary,
        )
        print(json.dumps(event, indent=2))
        return 0
    if args.command == "policy-evaluate":
        events = build_policy_log(
            PROJECT_ROOT / "outputs" / "baseline" / "telemetry.csv",
            PROJECT_ROOT / "outputs" / "agent" / "telemetry.csv",
            PROJECT_ROOT / "outputs" / "agent" / "policy_log.jsonl",
            args.episode_hours,
        )
        print(f"Wrote {len(events)} policy episodes.")
        return 0
    output = args.output or PROJECT_ROOT / "outputs" / args.mode
    return EnergyPlusRunner(settings, args.mode, output).run()


if __name__ == "__main__":
    raise SystemExit(main())
