"""Shared fixtures for API-level tests that need a small generated run
loaded into a fresh AppState (used by the trace and act endpoint tests)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state
from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    ConveyorSegment,
    EnvironmentEnvelope,
    LayoutSpec,
    LineSpec,
    MachineSpec,
    ParamRange,
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)
from lineage.datagen.models import RunConfig
from lineage.datagen.run import generate_run

TINY_RUN_ID = "tiny-api-test-run"


def _station(index: int, *, inspection: bool = False) -> StationSpec:
    station_id = f"ST-{index:02d}"
    sensor_id = f"{station_id}-SEN-1"
    return StationSpec(
        id=station_id,
        name=f"Station {index}",
        zone=Zone.BODY,
        sequence_index=index,
        sensors=[
            SensorSpec(
                id=sensor_id,
                kind=SensorKind.TORQUE,
                unit="N.m",
                sample_rate_hz=50.0,
                install_date=date(2020, 1, 1),
                last_calibration_date=date(2024, 1, 1),
                accuracy_class="1.0",
            )
        ],
        acquisition_mode=AcquisitionMode.INSTRUMENTED,
        is_inspection_station=inspection,
        cycle_time_nominal_s=10.0,
        commissioning_baseline=CommissioningBaseline(
            idle=ConditionStats(mean={sensor_id: 10.0}, std={sensor_id: 0.5}),
            loaded=ConditionStats(mean={sensor_id: 20.0}, std={sensor_id: 1.0}),
        ),
        changeable_params={"line_speed_pct": ParamRange(min=60.0, max=110.0, step=1.0)},
        machine=MachineSpec(
            model="M",
            install_year=2020,
            last_maintenance_date=date(2024, 1, 1),
            maintenance_interval_days=90,
            wear_curve_shape="linear",
        ),
        cost_per_hour=10.0,
        value_add_pct=1.0,
    )


def _tiny_line() -> LineSpec:
    stations = [_station(0), _station(1), _station(2, inspection=True)]
    return LineSpec(
        plant_name="Tiny Test Plant",
        site="Testville",
        stations=stations,
        layout=LayoutSpec(
            coordinates=[
                StationCoordinate(station_id=s.id, x_m=float(i * 10), y_m=0.0)
                for i, s in enumerate(stations)
            ],
            segments=[
                ConveyorSegment(
                    from_station_id=stations[i].id,
                    to_station_id=stations[i + 1].id,
                    distance_m=5.0,
                )
                for i in range(len(stations) - 1)
            ],
        ),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )


@pytest.fixture
def tiny_run_id() -> str:
    return TINY_RUN_ID


@pytest.fixture
def tiny_run_state(tmp_path) -> AppState:
    """A 3-station instrumented line with a 6-car generated run (seeded so a
    failed inspection is guaranteed), installed as the process AppState."""
    line = _tiny_line()
    config = RunConfig(
        run_id=TINY_RUN_ID,
        random_seed=7,
        num_cars=6,
        background_defect_rate=0.5,
        baseline_temp_c=22.0,
    )
    runs_root = tmp_path / "runs"
    generate_run(line, config, output_root=runs_root)
    state = AppState(line=line, runs_root=runs_root, models_root=tmp_path / "no_models_here")
    reset_app_state(state)
    return state


@pytest.fixture
def tiny_loaded_client(tiny_run_state):
    """A TestClient with the tiny run already loaded."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/replay/control", json={"action": "load", "run_id": TINY_RUN_ID}
        )
        assert response.status_code == 200
        yield client
