"""Tests for lineage.api.routes; to be filled in alongside real logic."""

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
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)
from lineage.datagen.models import RunConfig
from lineage.datagen.run import generate_run


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


def _setup_state(tmp_path) -> AppState:
    line = _tiny_line()
    config = RunConfig(
        run_id="api-test-run",
        random_seed=1,
        num_cars=3,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[],
        operator_shift_schedule=[],
    )
    runs_root = tmp_path / "runs"
    generate_run(line, config, output_root=runs_root)

    state = AppState(line=line, runs_root=runs_root)
    reset_app_state(state)
    return state


def test_get_line_returns_line_spec(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/line")
    assert response.status_code == 200
    assert response.json()["plant_name"] == "Test Plant"


def test_list_runs_and_load_and_ws_stream(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        runs = client.get("/api/runs").json()
        assert {"run_id": "api-test-run"} in runs

        loaded = client.post(
            "/api/replay/control", json={"action": "load", "run_id": "api-test-run"}
        )
        assert loaded.status_code == 200

        stepped = client.post("/api/replay/control", json={"action": "step"})
        assert stepped.status_code == 200

        with client.websocket_connect("/ws/line") as websocket:
            message = websocket.receive_json()
            assert message["run_id"] == "api-test-run"
            assert "stations" in message


def test_replay_control_without_load_returns_conflict(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        response = client.post("/api/replay/control", json={"action": "pause"})
    assert response.status_code == 409


def test_get_car_reads_from_cached_genealogy_store(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        loaded = client.post(
            "/api/replay/control", json={"action": "load", "run_id": "api-test-run"}
        )
        assert loaded.status_code == 200

        response = client.get("/api/cars/CAR-00000")
        assert response.status_code == 200
        body = response.json()
        assert body["car_id"] == "CAR-00000"
        assert len(body["visits"]) > 0
        assert body["visits"][0]["station_id"] == "ST-01"


def test_get_car_without_load_returns_conflict(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/cars/CAR-00000")
    assert response.status_code == 409


def test_get_unknown_car_returns_404(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/replay/control", json={"action": "load", "run_id": "api-test-run"})
        response = client.get("/api/cars/CAR-99999")
    assert response.status_code == 404


def test_operator_view_scoped_to_one_station(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/replay/control", json={"action": "load", "run_id": "api-test-run"})
        response = client.get("/api/view/operator", params={"station_id": "ST-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["station_id"] == "ST-01"
    assert body["station_name"] == "Only Station"
    assert "line_state" not in body
    assert "stations" not in body


def test_operator_view_includes_live_spc_verdict(tmp_path):
    """The live control/handover/calibration status added to OperatorView --
    must be a real, evaluated verdict once telemetry exists, not merely
    present-but-empty. ST-01 is instrumented with a real commissioning
    baseline and no seeded defects, so once enough of the run has played,
    its SPC verdict must be a genuine evaluation (never UNKNOWN, which would
    mean evaluate_spc silently found nothing to score)."""
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/replay/control", json={"action": "load", "run_id": "api-test-run"})
        for _ in range(5):
            client.post("/api/replay/control", json={"action": "step"})
        response = client.get("/api/view/operator", params={"station_id": "ST-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["spc_verdict"] is not None
    assert body["spc_verdict"]["station_id"] == "ST-01"
    assert body["spc_verdict"]["quantity"] == "ST-01-SEN-1"
    assert body["spc_verdict"]["state"] != "unknown"


def test_operator_view_unknown_station_returns_404(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/replay/control", json={"action": "load", "run_id": "api-test-run"})
        response = client.get("/api/view/operator", params={"station_id": "ST-99"})
    assert response.status_code == 404


def test_floor_supervisor_view_includes_full_line_state_and_alerts(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/replay/control", json={"action": "load", "run_id": "api-test-run"})
        response = client.get("/api/view/floor_supervisor")
    assert response.status_code == 200
    body = response.json()
    assert "line_state" in body
    assert "stations" in body["line_state"]
    assert isinstance(body["active_alert_station_ids"], list)


def test_plant_manager_view_includes_summary_counts(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/replay/control", json={"action": "load", "run_id": "api-test-run"})
        response = client.get("/api/view/plant_manager")
    assert response.status_code == 200
    body = response.json()
    assert "line_state" in body
    summary = body["summary"]
    assert summary["occupied_station_count"] >= 0
    assert summary["alarm_station_count"] >= 0


def test_leadership_view_has_no_per_station_detail(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/replay/control", json={"action": "load", "run_id": "api-test-run"})
        response = client.get("/api/view/leadership")
    assert response.status_code == 200
    body = response.json()
    assert "line_state" not in body
    assert "stations" not in body
    assert set(body.keys()) == {"summary"}


def test_role_views_without_load_return_conflict(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        assert client.get("/api/view/operator", params={"station_id": "ST-01"}).status_code == 409
        assert client.get("/api/view/floor_supervisor").status_code == 409
        assert client.get("/api/view/plant_manager").status_code == 409
        assert client.get("/api/view/leadership").status_code == 409
