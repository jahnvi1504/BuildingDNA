from __future__ import annotations


# Synthetic, deterministic Indian grid curve for an offline/reproducible demo.
# Units: kgCO2e/kWh. Night coal-heavy hours are higher; solar-rich midday is lower.
HOURLY_KG_CO2E_PER_KWH = (
    0.79, 0.80, 0.81, 0.81, 0.80, 0.78,
    0.75, 0.72, 0.69, 0.64, 0.59, 0.55,
    0.52, 0.53, 0.56, 0.61, 0.67, 0.72,
    0.76, 0.79, 0.81, 0.82, 0.81, 0.80,
)


def grid_carbon_intensity(hour: int) -> float:
    return HOURLY_KG_CO2E_PER_KWH[int(hour) % 24]

