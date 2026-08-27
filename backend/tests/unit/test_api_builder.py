"""Tests for lineage.api.routes.builder: draft start/insert/remove/move/save,
plus the sensor/baseline/distance/environment-envelope editing and
run-to-learn endpoints added for the node-graph Builder canvas."""

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
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)


def _segment_distance_violations(line: LineSpec) -> list[tuple[str, str, float, float]]:
    """Every segment whose distance_m doesn't match the actual Euclidean
    distance between its endpoints -- the geometry invariant from Task 3's
    test_example_42_segment_distances_match_actual_geometry, checked here at
    the API boundary the Builder canvas actually calls."""
    violations = []
    for segment in line.layout.segments:
        a = line.layout.coordinate_for(segment.from_station_id)
        b = line.layout.coordinate_for(segment.to_station_id)
        actual = ((b.x_m - a.x_m) ** 2 + (b.y_m - a.y_m) ** 2) ** 0.5
        if abs(actual - segment.distance_m) > 1e-9:
            violations.append(
                (segment.from_station_id, segment.to_station_id, segment.distance_m, actual)
            )
    return violations


def _sensor(sensor_id: str) -> SensorSpec:
    return SensorSpec(
        id=sensor_id,
        kind=SensorKind.TORQUE,
        unit="Nm",
        sample_rate_hz=10.0,
        install_date=date(2024, 1, 1),
        last_calibration_date=date(2024, 1, 1),
        accuracy_class="1.0",
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

        # ST-01 is now at index 1: moving up uses prepend_station to reach the front.
        up = client.post("/api/builder/draft/stations/ST-01/move", json={"direction": "up"})
        assert up.status_code == 200
        assert [s["id"] for s in up.json()["stations"]] == ["ST-01", "ST-02", "ST-03"]


def test_move_station_at_index_one_up_reaches_the_front(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/draft/stations/ST-02/move", json={"direction": "up"}
        )
    assert response.status_code == 200
    assert [s["id"] for s in response.json()["stations"]] == ["ST-02", "ST-01", "ST-03"]


def test_move_first_station_up_returns_400(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/draft/stations/ST-01/move", json={"direction": "up"}
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


# --- prepend endpoint ------------------------------------------------------


def test_prepend_endpoint_inserts_at_the_front_and_matches_geometry(tmp_path):
    _setup_state(tmp_path)
    new_station = _manual_station("ST-NEW", 0).model_dump(mode="json")
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/draft/stations/prepend", json={"station": new_station}
        )
    assert response.status_code == 200
    line = LineSpec.model_validate(response.json())
    assert [s.id for s in line.stations] == ["ST-NEW", "ST-01", "ST-02", "ST-03"]
    assert _segment_distance_violations(line) == []


def test_prepend_endpoint_needs_two_existing_stations(tmp_path):
    one_station_line = _three_station_line().remove_station("ST-03").remove_station("ST-02")
    state = AppState(line=one_station_line, lines_root=tmp_path / "lines")
    reset_app_state(state)
    new_station = _manual_station("ST-NEW", 0).model_dump(mode="json")
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post(
            "/api/builder/draft/stations/prepend", json={"station": new_station}
        )
    assert response.status_code == 400


# --- sensors endpoint -------------------------------------------------------


def test_update_sensors_endpoint_switches_manual_station_to_instrumented(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.put(
            "/api/builder/draft/stations/ST-02/sensors",
            json={
                "sensors": [_sensor("ST-02-TQ").model_dump(mode="json")],
                "acquisition_mode": "instrumented",
            },
        )
    assert response.status_code == 200
    line = LineSpec.model_validate(response.json())
    station = next(s for s in line.stations if s.id == "ST-02")
    assert station.acquisition_mode == AcquisitionMode.INSTRUMENTED
    assert [s.id for s in station.sensors] == ["ST-02-TQ"]


def test_update_sensors_endpoint_manual_station_with_no_sensors_is_not_an_error(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.put(
            "/api/builder/draft/stations/ST-02/sensors",
            json={"sensors": [], "acquisition_mode": "manual"},
        )
    assert response.status_code == 200
    line = LineSpec.model_validate(response.json())
    station = next(s for s in line.stations if s.id == "ST-02")
    assert station.sensors == []
    assert station.acquisition_mode == AcquisitionMode.MANUAL


def test_update_sensors_endpoint_rejects_sensors_on_a_manual_station(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.put(
            "/api/builder/draft/stations/ST-02/sensors",
            json={
                "sensors": [_sensor("ST-02-TQ").model_dump(mode="json")],
                "acquisition_mode": "manual",
            },
        )
    assert response.status_code == 400


def test_update_sensors_endpoint_unknown_station_returns_404(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.put(
            "/api/builder/draft/stations/ST-99/sensors",
            json={"sensors": [], "acquisition_mode": "manual"},
        )
    assert response.status_code == 404


# --- commissioning baseline endpoint ----------------------------------------


def test_update_baseline_endpoint_sets_and_clears_baseline(tmp_path):
    _setup_state(tmp_path)
    baseline = CommissioningBaseline(
        idle=ConditionStats(mean={"torque_nm": 1.0}, std={"torque_nm": 0.1}),
        loaded=ConditionStats(mean={"torque_nm": 5.0}, std={"torque_nm": 0.3}),
    )
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        set_response = client.put(
            "/api/builder/draft/stations/ST-02/commissioning_baseline",
            json={"baseline": baseline.model_dump(mode="json")},
        )
        assert set_response.status_code == 200
        line = LineSpec.model_validate(set_response.json())
        station = next(s for s in line.stations if s.id == "ST-02")
        assert station.commissioning_baseline is not None
        assert station.commissioning_baseline.idle.mean["torque_nm"] == 1.0

        clear_response = client.put(
            "/api/builder/draft/stations/ST-02/commissioning_baseline",
            json={"baseline": None},
        )
    assert clear_response.status_code == 200
    line = LineSpec.model_validate(clear_response.json())
    station = next(s for s in line.stations if s.id == "ST-02")
    assert station.commissioning_baseline is None


# --- segment distance endpoint ----------------------------------------------


def test_update_distance_endpoint_rescales_and_matches_geometry(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.put(
            "/api/builder/draft/segments/distance",
            json={"from_station_id": "ST-01", "to_station_id": "ST-02", "distance_m": 25.0},
        )
    assert response.status_code == 200
    line = LineSpec.model_validate(response.json())
    segment = line.layout.segment_between("ST-01", "ST-02")
    assert segment is not None
    assert segment.distance_m == 25.0
    assert _segment_distance_violations(line) == []


def test_update_distance_endpoint_unknown_segment_returns_400(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.put(
            "/api/builder/draft/segments/distance",
            json={"from_station_id": "ST-01", "to_station_id": "ST-03", "distance_m": 10.0},
        )
    assert response.status_code == 400


# --- environment envelope endpoint ------------------------------------------


def test_update_environment_envelope_endpoint_replaces_it(tmp_path):
    _setup_state(tmp_path)
    new_envelope = {
        "temp_min_c": 10.0,
        "temp_max_c": 30.0,
        "humidity_min_pct": 20.0,
        "humidity_max_pct": 70.0,
    }
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.put("/api/builder/draft/environment_envelope", json=new_envelope)
    assert response.status_code == 200
    line = LineSpec.model_validate(response.json())
    assert line.environment_envelope.temp_min_c == 10.0
    assert line.environment_envelope.temp_max_c == 30.0


def test_update_environment_envelope_endpoint_rejects_invalid_ranges(tmp_path):
    _setup_state(tmp_path)
    bad_envelope = {
        "temp_min_c": 30.0,
        "temp_max_c": 10.0,
        "humidity_min_pct": 20.0,
        "humidity_max_pct": 70.0,
    }
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.put("/api/builder/draft/environment_envelope", json=bad_envelope)
    assert response.status_code == 422


# --- run-to-learn commissioning endpoint ------------------------------------


def test_run_to_learn_endpoint_computes_real_statistics_from_samples():
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/builder/commissioning/run_to_learn",
            json={
                "accuracy_classes": {"torque_nm": "1.0"},
                "idle_nominal": {"torque_nm": 2.0},
                "loaded_nominal": {"torque_nm": 8.0},
                "sample_count": 200,
                "seed": 42,
            },
        )
    assert response.status_code == 200
    baseline = CommissioningBaseline.model_validate(response.json())
    assert baseline.idle.mean["torque_nm"] == pytest.approx(2.0, abs=0.5)
    assert baseline.loaded.mean["torque_nm"] == pytest.approx(8.0, abs=0.5)
    assert baseline.idle.std["torque_nm"] > 0.0


def test_run_to_learn_endpoint_is_reproducible_with_the_same_seed():
    payload = {
        "accuracy_classes": {"torque_nm": "1.0"},
        "idle_nominal": {"torque_nm": 2.0},
        "loaded_nominal": {"torque_nm": 8.0},
        "sample_count": 50,
        "seed": 7,
    }
    with TestClient(create_app()) as client:
        first = client.post("/api/builder/commissioning/run_to_learn", json=payload)
        second = client.post("/api/builder/commissioning/run_to_learn", json=payload)
    assert first.json() == second.json()


def test_run_to_learn_endpoint_rejects_mismatched_quantities():
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/builder/commissioning/run_to_learn",
            json={
                "accuracy_classes": {"torque_nm": "1.0"},
                "idle_nominal": {"torque_nm": 2.0},
                "loaded_nominal": {"rpm": 100.0},
            },
        )
    assert response.status_code == 400


# --- activate endpoint -------------------------------------------------------


def test_activate_endpoint_swaps_in_the_draft_as_the_live_line(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        client.delete("/api/builder/draft/stations/ST-02")
        response = client.post("/api/builder/activate")
    assert response.status_code == 200
    line = LineSpec.model_validate(response.json())
    assert [s.id for s in line.stations] == ["ST-01", "ST-03"]

    with TestClient(create_app()) as client:
        current = client.get("/api/line")
    assert current.status_code == 200
    assert [s["id"] for s in current.json()["stations"]] == ["ST-01", "ST-03"]


def test_activate_endpoint_requires_a_draft(tmp_path):
    _setup_state(tmp_path)
    with TestClient(create_app()) as client:
        response = client.post("/api/builder/activate")
    assert response.status_code == 409


def test_run_to_learn_endpoint_rejects_invalid_accuracy_class():
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/builder/commissioning/run_to_learn",
            json={
                "accuracy_classes": {"torque_nm": "not-a-number"},
                "idle_nominal": {"torque_nm": 2.0},
                "loaded_nominal": {"torque_nm": 8.0},
            },
        )
    assert response.status_code == 400
