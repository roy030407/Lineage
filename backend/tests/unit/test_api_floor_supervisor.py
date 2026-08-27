"""Tests for the Floor Supervisor view's new live alert-queue fields (SPC
alarms, high-risk cars, bottleneck warnings) and the newly-wired-up Act
proposal/approval and issue-assignment endpoints.

Uses the real default 400-car run (same seeded scenario test_spc_golden.py
checks retrospectively: torque drift at ST-06, cars 50-84) rather than a
synthetic tiny line, since these features need real telemetry/inspection
history to produce a genuine, non-trivial result -- a 1-station fixture
would only prove the response shape, not that the wiring actually works.
"""

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
    output_root = tmp_path_factory.mktemp("floor_supervisor_run")
    generate_run(line, config, output_root=output_root)
    return line, config, output_root


def _load_and_seek(line, output_root, run_id, seek_to) -> TestClient:
    """Loads the run, seeks to `seek_to`, and pauses -- the clock defaults to
    PLAYING (see replay/clock.py), and api/app.py's background tick loop
    advances it once per real second regardless of what a test just seeked
    to. Without pausing, sim time drifts forward between this call and
    whatever request the test makes next, non-deterministically -- a real
    bug caught while writing this test: the seeded ST-06 torque-drift window
    is only ~30 cars wide, easily ticked past before an assertion ever runs."""
    state = AppState(line=line, runs_root=output_root)
    reset_app_state(state)
    client = TestClient(create_app())
    client.__enter__()
    loaded = client.post("/api/replay/control", json={"action": "load", "run_id": run_id})
    assert loaded.status_code == 200
    seeked = client.post(
        "/api/replay/control", json={"action": "seek", "timestamp": seek_to.isoformat()}
    )
    assert seeked.status_code == 200
    paused = client.post("/api/replay/control", json={"action": "pause"})
    assert paused.status_code == 200
    return client


def test_floor_supervisor_view_returns_new_alert_queue_fields(default_run):
    line, config, output_root = default_run
    # Well into the torque-drift window (cars 50-84) so ST-06 has real
    # out-of-control telemetry, and enough of the line has run for
    # bottleneck/risk signal to exist. Empirically confirmed (not guessed):
    # +1h is too early for car 50 to have reached ST-06 yet; +2h reliably
    # lands inside the seeded window.
    seek_target = config.sim_start_time + timedelta(hours=2)
    client = _load_and_seek(line, output_root, config.run_id, seek_target)
    try:
        response = client.get("/api/view/floor_supervisor")
    finally:
        client.close()

    assert response.status_code == 200
    body = response.json()

    assert isinstance(body["spc_alarms"], list)
    assert isinstance(body["high_risk_cars"], list)
    assert isinstance(body["bottleneck_warnings"], list)
    assert body["issue_assignments"] == {}

    # The known seeded defect must produce a real alarm at its station, not
    # just an empty list that happens to type-check.
    station_ids_in_alarm = {alarm["station_id"] for alarm in body["spc_alarms"]}
    assert "ST-06" in station_ids_in_alarm
    st06_alarm = next(a for a in body["spc_alarms"] if a["station_id"] == "ST-06")
    assert st06_alarm["state"] == "out_of_control"

    # Every bottleneck warning must be a real forecast state, never HEALTHY
    # (that wouldn't be a warning) and never missing a station_id.
    for warning in body["bottleneck_warnings"]:
        assert warning["predicted_state"] in ("starved", "blocked")
        assert warning["station_id"]

    # Every high-risk car (if a trained model happens to be present locally)
    # must report a real HIGH risk_level and a sane stations_remaining, never
    # negative (which would mean the "next inspection station" lookup went
    # backwards).
    for car in body["high_risk_cars"]:
        assert car["risk_level"] == "high"
        assert car["stations_remaining"] >= 0


def test_floor_supervisor_assignment_endpoints_round_trip(default_run):
    line, config, output_root = default_run
    client = _load_and_seek(line, output_root, config.run_id, config.sim_start_time)
    try:
        assigned = client.post(
            "/api/floor_supervisor/assignments",
            json={"issue_id": "ST-06", "operator_id": "OP-ST-06-A"},
        )
        assert assigned.status_code == 200
        assert assigned.json() == {"ST-06": "OP-ST-06-A"}

        view = client.get("/api/view/floor_supervisor")
        assert view.json()["issue_assignments"] == {"ST-06": "OP-ST-06-A"}

        unassigned = client.delete("/api/floor_supervisor/assignments/ST-06")
        assert unassigned.status_code == 200
        assert unassigned.json() == {}
    finally:
        client.close()


def test_act_proposals_listed_and_approved(default_run):
    line, config, output_root = default_run
    client = _load_and_seek(line, output_root, config.run_id, config.sim_start_time)
    try:
        listed = client.get("/api/act/proposals")
        assert listed.status_code == 200
        proposals = listed.json()
        assert isinstance(proposals, list)

        if not proposals:
            pytest.skip("no Act proposals generated for this seeded run's failed inspections")

        proposal = proposals[0]
        assert proposal["status"] == "pending"

        approved = client.post(
            f"/api/act/proposals/{proposal['proposal_id']}/approve",
            json={"approver_id": "SUP-01"},
        )
        assert approved.status_code == 200
        record = approved.json()
        assert record["proposal_id"] == proposal["proposal_id"]
        assert record["approver_role"] == "floor_supervisor"
        assert record["decision"] == "approved"

        # The cached list reflects the approval -- not still "pending".
        relisted = client.get("/api/act/proposals").json()
        updated = next(p for p in relisted if p["proposal_id"] == proposal["proposal_id"])
        assert updated["status"] == "approved"
    finally:
        client.close()


def test_act_approve_unknown_proposal_returns_404(default_run):
    line, config, output_root = default_run
    client = _load_and_seek(line, output_root, config.run_id, config.sim_start_time)
    try:
        response = client.post(
            "/api/act/proposals/does-not-exist/approve", json={"approver_id": "SUP-01"}
        )
        assert response.status_code == 404
    finally:
        client.close()
