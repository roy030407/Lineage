"""Tests for the rebuilt Plant Manager view: weekly defect trends, rework
volume, recurring root causes, and maintenance schedule vs. predicted need --
no live line_state, per Task 6's explicit "weekly, not live" requirement.

Uses the real default 400-car run (same seeded scenario test_spc_golden.py
and test_api_floor_supervisor.py check: torque drift at ST-06, cars 50-84)
so recurring_root_causes has something real to find -- a synthetic tiny
line with no seeded defects would only prove the response shape."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state
from lineage.config.loader import load_line_spec
from lineage.datagen.cli import DEFAULT_LINE_PATH, build_default_run_config
from lineage.datagen.run import generate_run


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)
    output_root = tmp_path_factory.mktemp("plant_manager_run")
    generate_run(line, config, output_root=output_root)
    return line, config, output_root


def _load(line, output_root, config) -> TestClient:
    state = AppState(line=line, runs_root=output_root)
    reset_app_state(state)
    client = TestClient(create_app())
    client.__enter__()
    loaded = client.post("/api/replay/control", json={"action": "load", "run_id": config.run_id})
    assert loaded.status_code == 200
    # A full run has already completed by the time inspection.csv exists at
    # all -- Plant Manager reports over the whole run to date, not "as of
    # whatever the live clock happens to be", so seek to the end and pause
    # rather than leaving it mid-playback (irrelevant to correctness here,
    # but avoids the same seek/tick-drift class of flakiness found in
    # test_api_floor_supervisor.py).
    seek_target = config.sim_start_time + timedelta(hours=20)
    client.post(
        "/api/replay/control", json={"action": "seek", "timestamp": seek_target.isoformat()}
    )
    client.post("/api/replay/control", json={"action": "pause"})
    return client


def test_plant_manager_view_shape_has_no_live_state(default_run):
    line, config, output_root = default_run
    client = _load(line, output_root, config)
    try:
        response = client.get("/api/view/plant_manager")
    finally:
        client.close()

    assert response.status_code == 200
    body = response.json()
    assert "line_state" not in body
    assert "summary" not in body


def test_defect_rates_and_rework_reflect_real_inspection_results(default_run):
    line, config, output_root = default_run
    client = _load(line, output_root, config)
    try:
        response = client.get("/api/view/plant_manager")
    finally:
        client.close()
    body = response.json()

    by_station = body["defect_rate_by_station"]
    assert len(by_station) > 0
    for entry in by_station:
        assert entry["total_inspections"] > 0
        assert 0 <= entry["fail_count"] <= entry["total_inspections"]
        assert entry["fail_rate"] == pytest.approx(
            entry["fail_count"] / entry["total_inspections"]
        )

    by_zone = body["defect_rate_by_zone"]
    assert {z["zone"] for z in by_zone} <= {"body", "paint", "final"}
    # Zone totals must equal the sum of their member stations' totals -- not
    # a coincidentally-plausible number.
    zone_totals = {z["zone"]: z["total_inspections"] for z in by_zone}
    summed_by_zone: dict[str, int] = {}
    station_by_id = {s.id: s for s in line.stations}
    for entry in by_station:
        zone = station_by_id[entry["station_id"]].zone.value
        summed_by_zone[zone] = summed_by_zone.get(zone, 0) + entry["total_inspections"]
    assert zone_totals == summed_by_zone

    rework = body["rework"]
    assert rework["cars_requiring_rework"] > 0  # background defect rate + seeds guarantee some
    assert rework["cars_requiring_rework"] <= rework["total_cars_inspected"]
    assert rework["rework_rate"] == pytest.approx(
        rework["cars_requiring_rework"] / rework["total_cars_inspected"]
    )


def test_recurring_root_causes_surfaces_the_seeded_torque_drift_station(default_run):
    """ST-06's seeded torque drift (cars 50-84, 30 cars wide) is the single
    largest deliberate defect source in the default run -- it must show up
    among the recurring root causes, not just an empty or generic list."""
    line, config, output_root = default_run
    client = _load(line, output_root, config)
    try:
        response = client.get("/api/view/plant_manager")
    finally:
        client.close()
    body = response.json()

    causes = body["recurring_root_causes"]
    assert len(causes) > 0
    # Sorted descending by occurrence -- never accidentally unsorted.
    counts = [c["occurrence_count"] for c in causes]
    assert counts == sorted(counts, reverse=True)

    station_ids = {c["station_id"] for c in causes}
    assert "ST-06" in station_ids
    st06 = next(c for c in causes if c["station_id"] == "ST-06")
    assert st06["occurrence_count"] > 1
    assert len(st06["example_car_ids"]) > 0


def test_maintenance_status_covers_every_station_with_sane_values(default_run):
    line, config, output_root = default_run
    client = _load(line, output_root, config)
    try:
        response = client.get("/api/view/plant_manager")
    finally:
        client.close()
    body = response.json()

    statuses = body["maintenance_status"]
    assert len(statuses) == len(line.stations)
    for status in statuses:
        # Can legitimately be negative: gen_example_42.py spreads
        # last_maintenance_date across all 12 months of 2024, while this run
        # only simulates a few hours from Jan 1 -- some stations' configured
        # date is chronologically after the sim clock's current "now". A
        # real, if slightly odd, property of the sample data, not a bug in
        # this endpoint (machine_is_maintained already computed the same
        # elapsed-days value internally; this is the first time it's
        # surfaced as a raw number instead of just a boolean comparison).
        assert isinstance(status["days_since_maintenance"], float)
        assert status["maintenance_interval_days"] > 0
        # days_until_due can be negative (overdue) -- that's real and
        # meaningful, not a bug, so only check it's internally consistent.
        assert status["days_until_due"] == pytest.approx(
            status["maintenance_interval_days"] - status["days_since_maintenance"]
        )
        if status["recent_wear_state"] is not None:
            assert status["recent_wear_state"] >= 0
