from __future__ import annotations

import calendar
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunPeriod:
    begin_month: int
    begin_day: int
    end_month: int
    end_day: int


def parse_run_period(value: str) -> RunPeriod:
    """Parse and validate an inclusive MM-DD:MM-DD EnergyPlus run period."""
    try:
        begin, end = value.split(":", maxsplit=1)
        begin_month, begin_day = (int(part) for part in begin.split("-", maxsplit=1))
        end_month, end_day = (int(part) for part in end.split("-", maxsplit=1))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid representative period {value!r}; expected MM-DD:MM-DD"
        ) from exc

    for label, month, day in (
        ("begin", begin_month, begin_day),
        ("end", end_month, end_day),
    ):
        if not 1 <= month <= 12:
            raise ValueError(f"Invalid {label} month in representative period {value!r}")
        if not 1 <= day <= calendar.monthrange(2021, month)[1]:
            raise ValueError(f"Invalid {label} day in representative period {value!r}")

    return RunPeriod(begin_month, begin_day, end_month, end_day)


def build_representative_idf(
    source_path: Path,
    destination_path: Path,
    idd_path: Path,
    configured_periods: list[str],
) -> Path:
    """Copy an IDF and replace its run periods without changing the source model."""
    from eppy.modeleditor import IDF

    if not configured_periods:
        raise ValueError("ECOLOOP_REPRESENTATIVE_PERIODS must contain at least one period")

    periods = [parse_run_period(value) for value in configured_periods]
    IDF.setiddname(str(idd_path))
    idf = IDF(str(source_path))
    for existing in list(idf.idfobjects["RUNPERIOD"]):
        idf.removeidfobject(existing)
    for index, period in enumerate(periods, start=1):
        idf.newidfobject(
            "RUNPERIOD",
            Name=f"EcoLoop Representative Period {index}",
            Begin_Month=period.begin_month,
            Begin_Day_of_Month=period.begin_day,
            End_Month=period.end_month,
            End_Day_of_Month=period.end_day,
            Day_of_Week_for_Start_Day="Sunday",
            Use_Weather_File_Holidays_and_Special_Days="Yes",
            Use_Weather_File_Daylight_Saving_Period="Yes",
            Apply_Weekend_Holiday_Rule="No",
            Use_Weather_File_Rain_Indicators="Yes",
            Use_Weather_File_Snow_Indicators="Yes",
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    idf.saveas(str(destination_path))
    return destination_path
