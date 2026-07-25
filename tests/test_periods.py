import pytest

from ecoloop.periods import RunPeriod, parse_run_period


def test_parse_representative_period() -> None:
    assert parse_run_period("07-15:07-21") == RunPeriod(7, 15, 7, 21)


@pytest.mark.parametrize("value", ["07-32:08-01", "13-01:13-07", "one-week"])
def test_reject_invalid_representative_period(value: str) -> None:
    with pytest.raises(ValueError):
        parse_run_period(value)
