"""Golden-file regression harness: parametrized per frozen scenario once scenarios exist."""

from datetime import date
from pathlib import Path

import yaml

from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    LineSpec,
    MachineSpec,
    ParamRange,
    SensorKind,
    SensorSpec,
    StationSpec,
    Zone,
)

EXAMPLE_LINE_PATH = Path(__file__).parents[2] / "data" / "lines" / "example_42.yaml"
GOLDEN_PATH = Path(__file__).parent / "config" / "example_42_after_insert_at_17.yaml"


def _new_pretreatment_station() -> StationSpec:
    sensors = [
        SensorSpec(
            id="ST-43-SEN-1",
            kind=SensorKind.THERMAL,
            unit="C",
            sample_rate_hz=1.0,
            install_date=date(2023, 6, 1),
            last_calibration_date=date(2024, 1, 15),
            accuracy_class="0.5",
        ),
        SensorSpec(
            id="ST-43-SEN-2",
            kind=SensorKind.CYCLE_TIME,
            unit="s",
            sample_rate_hz=1.0,
            install_date=date(2023, 6, 1),
            last_calibration_date=date(2024, 1, 15),
            accuracy_class="1.0",
        ),
    ]
    baseline = CommissioningBaseline(
        idle=ConditionStats(
            mean={"ST-43-SEN-1": 22.0, "ST-43-SEN-2": 0.0},
            std={"ST-43-SEN-1": 0.4, "ST-43-SEN-2": 0.0},
        ),
        loaded=ConditionStats(
            mean={"ST-43-SEN-1": 45.0, "ST-43-SEN-2": 90.0},
            std={"ST-43-SEN-1": 1.2, "ST-43-SEN-2": 2.5},
        ),
    )
    return StationSpec(
        id="ST-43",
        name="Pretreatment Dip Tank",
        zone=Zone.PAINT,
        sequence_index=0,  # overwritten by insert_station
        sensors=sensors,
        acquisition_mode=AcquisitionMode.INSTRUMENTED,
        cycle_time_nominal_s=90.0,
        commissioning_baseline=baseline,
        changeable_params={"line_speed_pct": ParamRange(min=80.0, max=110.0, step=1.0)},
        readable_params=["ST-43-SEN-1", "ST-43-SEN-2"],
        machine=MachineSpec(
            model="Durr EcoClean Dip Line",
            install_year=2023,
            last_maintenance_date=date(2024, 1, 10),
            maintenance_interval_days=90,
            wear_curve_shape="bathtub",
        ),
        cost_per_hour=95.0,
        value_add_pct=2.0,
    )


def test_example_42_insert_at_position_17_matches_golden():
    line = LineSpec.from_yaml(EXAMPLE_LINE_PATH)

    after_id = line.stations[15].id  # 1-based position 16, last body station
    assert after_id == "ST-16"

    new_station = _new_pretreatment_station()
    updated = line.insert_station(new_station, after_station_id=after_id)

    assert updated.stations[16].id == "ST-43"
    assert updated.stations[16].sequence_index == 16

    actual = yaml.safe_load(updated.to_yaml())
    expected = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))

    assert actual == expected
