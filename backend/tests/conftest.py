"""Shared pytest fixtures (LineSpecs, tick engine, etc.)."""

from datetime import date

import pytest

from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    EnvironmentEnvelope,
    LayoutSpec,
    LineSpec,
    MachineSpec,
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)


@pytest.fixture
def tiny_line() -> LineSpec:
    """A minimal single-station line for API-level tests that only need *a*
    valid LineSpec, not a realistic one.

    Deliberately a fixture rather than an importable helper: there is no
    tests/__init__.py, so conftest discovery is the only sharing mechanism
    that does not require adding one.

    Shape copied from tests/unit/test_api_routes.py's own _tiny_line, which
    is the proven reference for what generate_run accepts. That file keeps
    its private copy untouched -- existing tests are the spec, so this is
    additive rather than a refactor of them.
    """
    machine = MachineSpec(
        model="M",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )
    sensor = SensorSpec(
        id="ST-01-SEN-1",
        kind=SensorKind.TORQUE,
        unit="N.m",
        sample_rate_hz=50.0,
        install_date=date(2020, 1, 1),
        last_calibration_date=date(2024, 1, 1),
        accuracy_class="1.0",
    )
    baseline = CommissioningBaseline(
        idle=ConditionStats(mean={"ST-01-SEN-1": 10.0}, std={"ST-01-SEN-1": 0.5}),
        loaded=ConditionStats(mean={"ST-01-SEN-1": 20.0}, std={"ST-01-SEN-1": 1.0}),
    )
    stations = [
        StationSpec(
            id="ST-01",
            name="Only Station",
            zone=Zone.BODY,
            sequence_index=0,
            sensors=[sensor],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=baseline,
            machine=machine,
            cost_per_hour=10.0,
            value_add_pct=1.0,
        )
    ]
    return LineSpec(
        plant_name="Test Plant",
        site="Testville",
        stations=stations,
        layout=LayoutSpec(
            coordinates=[StationCoordinate(station_id="ST-01", x_m=0.0, y_m=0.0)], segments=[]
        ),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )
