from pathlib import Path

from ecoloop.state import LiveState
from ecoloop.tools import ControlTools


def test_required_telemetry_and_setpoint_tools() -> None:
    state = LiveState()
    state.update(
        zone_temperatures_c={"Core_ZN": 24.2},
        pmv={"Core_ZN": 0.07},
        energy_kwh=12.5,
        hour=12,
    )
    tools = ControlTools(state, Path("model.idf"), Path("Energy+.idd"))
    assert tools.get_zone_temps() == {"Core_ZN": 24.2}
    assert tools.get_pmv() == {"Core_ZN": 0.07}
    assert tools.get_energy_kwh() == 12.5
    result = tools.set_setpoint("Core_ZN", 25.0)
    assert result["queued"] is True
    assert state.drain_setpoints()[0].value_c == 25.0

