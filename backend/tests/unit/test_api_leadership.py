"""Tests for the rebuilt Leadership view: real cost/value-add totals and a
sensor-retrofit ranking grounded in economic weight plus Task 6's real
recurring-root-cause data -- never a fabricated dollar "ROI" figure, and
never the old live occupied/alarm/buffer summary triple.

Uses the real default 400-car run (same seeded scenario test_api_floor_supervisor.py
and test_api_plant_manager.py check: an unflagged operator-handover at
manual station ST-02, the single largest recurring defect source) so
sensor_retrofit_candidates has something real to rank, not just a shape to
type-check."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state
from lineage.config.loader import load_line_spec
from lineage.config.specs import AcquisitionMode
from lineage.datagen.cli import DEFAULT_LINE_PATH, build_default_run_config
from lineage.datagen.run import generate_run


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)
    output_root = tmp_path_factory.mktemp("leadership_run")
    generate_run(line, config, output_root=output_root)
    return line, config, output_root


def _load(line, output_root, config) -> TestClient:
    state = AppState(line=line, runs_root=output_root)
    reset_app_state(state)
    client = TestClient(create_app())
    client.__enter__()
    loaded = client.post("/api/replay/control", json={"action": "load", "run_id": config.run_id})
    assert loaded.status_code == 200
    seek_target = config.sim_start_time + timedelta(hours=20)
    client.post(
        "/api/replay/control", json={"action": "seek", "timestamp": seek_target.isoformat()}
    )
    client.post("/api/replay/control", json={"action": "pause"})
    return client


def test_cost_totals_and_value_added_ratio_are_real_arithmetic(default_run):
    line, config, output_root = default_run
    client = _load(line, output_root, config)
    try:
        response = client.get("/api/view/leadership")
    finally:
        client.close()
    assert response.status_code == 200
    body = response.json()

    expected_total_cost = sum(s.cost_per_hour for s in line.stations)
    expected_value_added = sum(
        s.cost_per_hour * (s.value_add_pct / 100.0) for s in line.stations
    )
    assert body["total_cost_per_hour"] == pytest.approx(expected_total_cost)
    assert body["total_value_added_cost_per_hour"] == pytest.approx(expected_value_added)
    assert body["value_added_ratio"] == pytest.approx(expected_value_added / expected_total_cost)

    # Zone totals must equal the sum of their member stations', not a
    # coincidentally-plausible number.
    by_zone = {z["zone"]: z for z in body["cost_by_zone"]}
    for zone in ("body", "paint", "final"):
        stations_in_zone = [s for s in line.stations if s.zone.value == zone]
        assert by_zone[zone]["total_cost_per_hour"] == pytest.approx(
            sum(s.cost_per_hour for s in stations_in_zone)
        )


def test_sensor_retrofit_candidates_are_manual_stations_only(default_run):
    line, config, output_root = default_run
    client = _load(line, output_root, config)
    try:
        response = client.get("/api/view/leadership")
    finally:
        client.close()
    body = response.json()

    candidates = body["sensor_retrofit_candidates"]
    assert len(candidates) > 0
    manual_station_ids = {
        s.id for s in line.stations if s.acquisition_mode == AcquisitionMode.MANUAL
    }
    candidate_ids = {c["station_id"] for c in candidates}
    assert candidate_ids <= manual_station_ids
    # Every manual station has no sensors by construction (the config
    # invariant test_config.py's test_manual_station_with_sensors_rejected
    # enforces) -- every manual station should appear as a candidate.
    assert candidate_ids == manual_station_ids

    # Sorted by recurring defect occurrences first, then economic weight --
    # never accidentally unsorted.
    keys = [(c["recurring_defect_occurrences"], c["economic_weight"]) for c in candidates]
    assert keys == sorted(keys, reverse=True)


def test_st02_ranks_first_as_the_seeded_operator_handover_station(default_run):
    """ST-02 is a manual station and the seeded *unflagged* operator-handover
    origin -- Task 6's Plant Manager test already confirmed it's the largest
    recurring root cause (182 occurrences vs. ST-06's 27). It must rank
    first here too, since this ranking reuses that exact same real data."""
    line, config, output_root = default_run
    client = _load(line, output_root, config)
    try:
        response = client.get("/api/view/leadership")
    finally:
        client.close()
    body = response.json()

    candidates = body["sensor_retrofit_candidates"]
    top = candidates[0]
    assert top["station_id"] == "ST-02"
    assert top["recurring_defect_occurrences"] > 0
