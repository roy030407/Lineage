"""Tests for lineage.api.routes.builder: draft start/insert/remove/move/save."""

from datetime import date

from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state
from lineage.config.specs import (
    AcquisitionMode,
    ConveyorSegment,
    EnvironmentEnvelope,
    LayoutSpec,
    LineSpec,
    MachineSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)


def _machine() -> MachineSpec:
    return MachineSpec(
        model="M",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )


def _manual_station(station_id: str, sequence_index: int) -> StationSpec:
    return StationSpec(
        id=station_id,
        name=f"Station {station_id}",
        zone=Zone.BODY,
        sequence_index=sequence_index,
        acquisition_mode=AcquisitionMode.MANUAL,
        cycle_time_nominal_s=10.0,
        machine=_machine(),
        cost_per_hour=10.0,
        value_add_pct=1.0,
    )


def _three_station_line() -> LineSpec:
    stations = [
        _manual_station("ST-01", 0),
        _manual_station("ST-02", 1),
        _manual_station("ST-03", 2),
    ]
    return LineSpec(
        plant_name="Test Plant",
        site="Testville",
        stations=stations,
        layout=LayoutSpec(
            coordinates=[
                StationCoordinate(station_id="ST-01", x_m=0.0, y_m=0.0),
                StationCoordinate(station_id="ST-02", x_m=10.0, y_m=0.0),
                StationCoordinate(station_id="ST-03", x_m=20.0, y_m=0.0),
            ],
            segments=[
                ConveyorSegment(from_station_id="ST-01", to_station_id="ST-02", distance_m=10.0),
                ConveyorSegment(from_station_id="ST-02", to_station_id="ST-03", distance_m=10.0),
            ],
        ),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )


def _setup_state(tmp_path) -> AppState:
    state = AppState(line=_three_station_line(), lines_root=tmp_path / "lines")
    reset_app_state(state)
    return state


def test_start_draft_requires_a_loaded_line():
    reset_app_state(AppState(line=None))
    with TestClient(create_app()) as client:
        response = client.post("/api/builder/draft/start")
    assert response.status_code == 409


def test_get_draft_without_start_returns_conflict(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/api/builder/draft")
    assert response.status_code == 409


def test_start_draft_then_insert_station(tmp_path):
    _setup_state(tmp_path)
    new_station = _manual_station("ST-NEW", 0).model_dump(mode="json")
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/draft/stations",
            json={"station": new_station, "after_station_id": "ST-01"},
        )
    assert response.status_code == 200
    ids = [s["id"] for s in response.json()["stations"]]
    assert ids == ["ST-01", "ST-NEW", "ST-02", "ST-03"]


def test_insert_after_unknown_station_returns_400(tmp_path):
    _setup_state(tmp_path)
    new_station = _manual_station("ST-NEW", 0).model_dump(mode="json")
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/draft/stations",
            json={"station": new_station, "after_station_id": "ST-99"},
        )
    assert response.status_code == 400


def test_remove_station(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.delete("/api/builder/draft/stations/ST-02")
    assert response.status_code == 200
    ids = [s["id"] for s in response.json()["stations"]]
    assert ids == ["ST-01", "ST-03"]


def test_remove_unknown_station_returns_400(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.delete("/api/builder/draft/stations/ST-99")
    assert response.status_code == 400


def test_move_station_up_and_down(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")

        down = client.post("/api/builder/draft/stations/ST-01/move", json={"direction": "down"})
        assert down.status_code == 200
        assert [s["id"] for s in down.json()["stations"]] == ["ST-02", "ST-01", "ST-03"]

        up = client.post("/api/builder/draft/stations/ST-01/move", json={"direction": "up"})
        assert up.status_code == 400  # ST-01 is now at index 1: moving up needs "insert at head"


def test_move_first_station_up_returns_400(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/draft/stations/ST-02/move", json={"direction": "up"}
        )
    assert response.status_code == 400


def test_move_last_station_down_returns_400(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/draft/stations/ST-03/move", json={"direction": "down"}
        )
    assert response.status_code == 400


def test_save_draft_writes_new_yaml_file(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post("/api/builder/save", json={"filename": "my_new_line.yaml"})
    assert response.status_code == 200
    saved_path = tmp_path / "lines" / "my_new_line.yaml"
    assert saved_path.exists()
    assert LineSpec.from_yaml(saved_path).plant_name == "Test Plant"


def test_save_draft_refuses_to_overwrite_existing_file(tmp_path):
    state = _setup_state(tmp_path)
    state.lines_root.mkdir(parents=True, exist_ok=True)
    (state.lines_root / "already_there.yaml").write_text("plant_name: x", encoding="utf-8")
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post("/api/builder/save", json={"filename": "already_there.yaml"})
    assert response.status_code == 409


def test_save_draft_rejects_path_traversal_filename(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/save", json={"filename": "../../etc/passwd.yaml"}
        )
    assert response.status_code == 400
