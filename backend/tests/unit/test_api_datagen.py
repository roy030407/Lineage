"""Tests for lineage.api.routes.datagen: the on-demand "Simulate" endpoint."""

from datetime import date

from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state
from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    EnvironmentEnvelope,
    LayoutSpec,
    LineSpec,
    MachineSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)


def _tiny_line() -> LineSpec:
    machine = MachineSpec(
        model="M",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )
    stations = [
        StationSpec(
            id="ST-01",
            name="Only Station",
            zone=Zone.BODY,
            sequence_index=0,
            acquisition_mode=AcquisitionMode.MANUAL,
            is_inspection_station=True,
            cycle_time_nominal_s=10.0,
            readable_params=["torque_nm"],
            commissioning_baseline=CommissioningBaseline(
                idle=ConditionStats(mean={"torque_nm": 10.0}, std={"torque_nm": 0.5}),
                loaded=ConditionStats(mean={"torque_nm": 20.0}, std={"torque_nm": 1.0}),
            ),
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


def _setup_state(tmp_path) -> AppState:
    state = AppState(line=_tiny_line(), runs_root=tmp_path / "runs")
    reset_app_state(state)
    return state


def test_simulate_without_a_line_loaded_returns_404():
    reset_app_state(AppState(line=None))
    with TestClient(create_app()) as client:
        response = client.post("/api/datagen/simulate")
    assert response.status_code == 404


def test_simulate_generates_and_loads_a_fresh_run(tmp_path):
    state = _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        response = client.post("/api/datagen/simulate")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"].startswith("simulated_")
    assert body["num_cars"] == 400

    # The endpoint's whole point is that the run is immediately playable,
    # not just written to disk -- load_run_into_state must actually have run.
    assert state.engine is not None
    assert state.current_run_dir == state.runs_root / body["run_id"]
    assert (state.runs_root / body["run_id"] / "telemetry.csv").exists()


def test_two_simulate_calls_produce_different_runs(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        first = client.post("/api/datagen/simulate")
        second = client.post("/api/datagen/simulate")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["run_id"] != second.json()["run_id"]
