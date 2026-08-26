"""Tests for lineage.api.routes.predict: metrics/trend endpoints, and the
graceful "no trained model" degradation in the 'load' action."""

from datetime import date, datetime, timedelta

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
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)
from lineage.datagen.models import RunConfig
from lineage.datagen.run import generate_run
from lineage.predict.ledger import PredictionLedger, PredictionOutcome, PredictionRecord

T0 = datetime(2024, 1, 1, 8, 0)


def _tiny_line() -> LineSpec:
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
            is_inspection_station=True,
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


def _setup_state(tmp_path, with_ledger: bool = False) -> AppState:
    line = _tiny_line()
    config = RunConfig(
        run_id="predict-api-test-run",
        random_seed=1,
        num_cars=3,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[],
        operator_shift_schedule=[],
    )
    runs_root = tmp_path / "runs"
    generate_run(line, config, output_root=runs_root)

    # models_root deliberately points at an empty directory -- no risk_v1
    # subfolder -- mirroring a fresh clone with data/models/ gitignored.
    state = AppState(line=line, runs_root=runs_root, models_root=tmp_path / "no_models_here")
    if with_ledger:
        state.prediction_ledger = PredictionLedger()
    reset_app_state(state)
    return state


def test_metrics_without_any_run_loaded_returns_conflict(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/predict/metrics")
    assert response.status_code == 409


def test_load_without_a_trained_model_leaves_ledger_unavailable(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        loaded = client.post(
            "/api/replay/control",
            json={"action": "load", "run_id": "predict-api-test-run"},
        )
        assert loaded.status_code == 200  # the run itself still loads fine

        response = client.get("/api/predict/metrics")
    assert response.status_code == 409


def test_metrics_reflects_ledger_records(tmp_path):
    state = _setup_state(tmp_path, with_ledger=True)
    state.prediction_ledger.record(
        PredictionRecord(
            car_id="CAR-001",
            station_id="ST-01",
            model_version="v1",
            risk_level="high",
            probability=0.9,
            confidence=1.0,
            predicted_at=T0,
            outcome=PredictionOutcome.MATERIALIZED,
            resolved_at=T0,
            actual_result="fail",
        )
    )
    state.prediction_ledger.record(
        PredictionRecord(
            car_id="CAR-002",
            station_id="ST-01",
            model_version="v1",
            risk_level="high",
            probability=0.9,
            confidence=1.0,
            predicted_at=T0,
            outcome=PredictionOutcome.NOT_MATERIALIZED,
            resolved_at=T0,
            actual_result="pass",
        )
    )

    with TestClient(create_app()) as client:
        response = client.get("/api/predict/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["true_positive"] == 1
    assert body["false_positive"] == 1
    assert body["precision"] == 0.5


def test_metrics_by_station_groups_correctly(tmp_path):
    state = _setup_state(tmp_path, with_ledger=True)
    for station_id in ("ST-01", "ST-02"):
        state.prediction_ledger.record(
            PredictionRecord(
                car_id="CAR-001",
                station_id=station_id,
                model_version="v1",
                risk_level="high",
                probability=0.9,
                confidence=1.0,
                predicted_at=T0,
                outcome=PredictionOutcome.MATERIALIZED,
                resolved_at=T0,
                actual_result="fail",
            )
        )

    with TestClient(create_app()) as client:
        response = client.get("/api/predict/metrics/by_station")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"ST-01", "ST-02"}
    assert body["ST-01"]["true_positive"] == 1


def test_trend_endpoint_returns_null_with_insufficient_data(tmp_path):
    state = _setup_state(tmp_path, with_ledger=True)
    state.prediction_ledger.record(
        PredictionRecord(
            car_id="CAR-001",
            station_id="ST-01",
            model_version="v1",
            risk_level="high",
            probability=0.9,
            confidence=1.0,
            predicted_at=T0,
            outcome=PredictionOutcome.MATERIALIZED,
            resolved_at=T0,
            actual_result="fail",
        )
    )

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/predict/trend/ST-01",
            params={"intervention_at": (T0 + timedelta(hours=1)).isoformat()},
        )
    assert response.status_code == 200
    assert response.json() is None
