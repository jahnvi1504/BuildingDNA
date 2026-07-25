from __future__ import annotations

import argparse
from pathlib import Path

from ecoloop.config import PROJECT_ROOT, settings
from ecoloop.simulation import EnergyPlusRunner


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="ecoloop")
    commands = root.add_subparsers(dest="command", required=True)
    simulate = commands.add_parser("simulate", help="Run live EnergyPlus control")
    simulate.add_argument("--mode", choices=("baseline", "agent"), required=True)
    simulate.add_argument("--output", type=Path)
    commands.add_parser("mcp", help="Run MCP server over stdio")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "mcp":
        from ecoloop.mcp_server import main as run_mcp

        run_mcp()
        return 0
    output = args.output or PROJECT_ROOT / "outputs" / args.mode
    return EnergyPlusRunner(settings, args.mode, output).run()


if __name__ == "__main__":
    raise SystemExit(main())
