from ecoloop.config import Settings
from ecoloop.reflex import ReflexController
from ecoloop.state import LiveState, SetpointRequest


def test_reflex_clamps_unsafe_supervisory_request() -> None:
    state = LiveState()
    controller = ReflexController(Settings(_env_file=None), state)
    state.queue_setpoint(SetpointRequest(zone="Core_ZN", value_c=31.0, kind="cooling"))
    decision = controller.step({"Core_ZN": 24.0}, occupied=True)
    assert decision.cooling_c == 26.0
    assert decision.intervened


def test_reflex_runs_without_reason_layer() -> None:
    controller = ReflexController(Settings(_env_file=None), LiveState())
    occupied = controller.step({"Core_ZN": 24.0}, occupied=True)
    unoccupied = controller.step({"Core_ZN": 24.0}, occupied=False)
    assert occupied.heating_c == 20.0
    assert occupied.cooling_c == 25.4
    assert unoccupied.heating_c == 15.56
    assert unoccupied.cooling_c == 29.44


def test_reflex_restores_safety_on_extreme_temperature() -> None:
    controller = ReflexController(Settings(_env_file=None), LiveState())
    decision = controller.step({"Core_ZN": 29.0}, occupied=False)
    assert decision.cooling_c == 26.0
    assert decision.intervened

