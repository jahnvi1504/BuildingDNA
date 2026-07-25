from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ecoloop.config import settings
from ecoloop.state import LiveState
from ecoloop.tools import ControlTools


live_state = LiveState()
control = ControlTools(
    state=live_state,
    idf_path=settings.resolved(settings.ecoloop_idf),
    idd_path=settings.resolved(settings.energyplus_home) / "Energy+.idd",
)
mcp = FastMCP("Eco-Loop EnergyPlus")


@mcp.tool()
def get_zone_temps() -> dict[str, float]:
    return control.get_zone_temps()


@mcp.tool()
def get_pmv() -> dict[str, float]:
    return control.get_pmv()


@mcp.tool()
def get_energy_kwh() -> float:
    return control.get_energy_kwh()


@mcp.tool()
def get_grid_carbon_intensity() -> float:
    return control.get_grid_carbon_intensity()


@mcp.tool()
def set_setpoint(zone: str, value: float, kind: str = "cooling") -> dict:
    return control.set_setpoint(zone, value, kind)


@mcp.tool()
def adjust_schedule(schedule_name: str, ops: list[dict]) -> dict:
    return control.adjust_schedule(schedule_name, ops)


@mcp.tool()
def get_error_log() -> list[str]:
    return control.get_error_log()


@mcp.tool()
def patch_idf(diff: dict) -> dict:
    return control.patch_idf(diff)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

