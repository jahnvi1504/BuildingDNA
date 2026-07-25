from ecoloop.carbon import HOURLY_KG_CO2E_PER_KWH, grid_carbon_intensity


def test_carbon_curve_is_complete_and_plausible() -> None:
    assert len(HOURLY_KG_CO2E_PER_KWH) == 24
    assert all(0.4 <= value <= 1.0 for value in HOURLY_KG_CO2E_PER_KWH)
    assert grid_carbon_intensity(24) == grid_carbon_intensity(0)
    assert grid_carbon_intensity(12) < grid_carbon_intensity(3)

