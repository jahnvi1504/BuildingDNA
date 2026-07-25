from __future__ import annotations

from dataclasses import dataclass

from ecoloop.config import Settings
from ecoloop.state import LiveState


@dataclass(slots=True)
class ReflexDecision:
    heating_c: float
    cooling_c: float
    intervened: bool
    reason: str


class ReflexController:
    """Zero-latency safety controller; has no network or LLM dependency."""

    def __init__(self, settings: Settings, state: LiveState) -> None:
        self.settings = settings
        self.state = state
        self.heating_c = settings.default_heating_setpoint_c
        self.cooling_c = settings.default_cooling_setpoint_c
        self.supervisory_heating_c: float | None = None
        self.supervisory_cooling_c: float | None = None

    def step(self, temperatures: dict[str, float], occupied: bool) -> ReflexDecision:
        intervened = False
        reasons: list[str] = []
        base_heating = self.settings.occupied_heating_min_c if occupied else 15.56
        base_cooling = 25.4 if occupied else 29.44

        for request in self.state.drain_setpoints():
            value = float(request.value_c)
            if request.kind == "cooling":
                safe = min(max(value, base_heating + 1.0), self.settings.absolute_max_c)
                if occupied:
                    safe = min(safe, self.settings.occupied_cooling_max_c)
                intervened |= safe != value
                self.supervisory_cooling_c = safe
            else:
                safe = max(min(value, base_cooling - 1.0), self.settings.absolute_min_c)
                if occupied:
                    safe = max(safe, self.settings.occupied_heating_min_c)
                intervened |= safe != value
                self.supervisory_heating_c = safe
            if safe != value:
                reasons.append(f"clamped {request.kind} request {value:.1f}C to {safe:.1f}C")

        self.heating_c = self.supervisory_heating_c or base_heating
        self.cooling_c = self.supervisory_cooling_c or base_cooling
        if not occupied:
            # Preserve the prototype's night/weekend setback unless actual
            # temperatures approach the absolute safety boundary.
            self.heating_c = min(self.heating_c, base_heating)
            self.cooling_c = max(self.cooling_c, base_cooling)

        if temperatures:
            coldest = min(temperatures.values())
            hottest = max(temperatures.values())
            if coldest < self.settings.absolute_min_c:
                self.heating_c = max(self.heating_c, self.settings.occupied_heating_min_c)
                intervened = True
                reasons.append(f"cold-zone override at {coldest:.1f}C")
            if hottest > self.settings.absolute_max_c:
                self.cooling_c = min(self.cooling_c, self.settings.occupied_cooling_max_c)
                intervened = True
                reasons.append(f"hot-zone override at {hottest:.1f}C")

        if self.heating_c > self.cooling_c - 1.0:
            self.heating_c = self.cooling_c - 1.0
            intervened = True
            reasons.append("restored 1C thermostat deadband")

        return ReflexDecision(
            heating_c=self.heating_c,
            cooling_c=self.cooling_c,
            intervened=intervened,
            reason="; ".join(reasons) or "setpoints within safety envelope",
        )
