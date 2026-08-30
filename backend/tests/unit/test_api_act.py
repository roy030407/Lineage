"""Tests for lineage.api.routes.act: proposal dedup, idempotent approval,
setpoint tracking, and the simulate endpoint."""

from fastapi.testclient import TestClient


def _proposals(client: TestClient) -> list[dict]:
    response = client.get("/api/act/proposals")
    assert response.status_code == 200
    return response.json()


def test_proposals_are_deduped_by_station_and_parameter(tiny_loaded_client):
    proposals = _proposals(tiny_loaded_client)

    assert proposals, "the seeded run must produce at least one failed inspection"
    targets = [(p["station_id"], p["parameter_name"]) for p in proposals]
    assert len(targets) == len(set(targets)), "one proposal per (station, parameter)"


def test_approve_is_idempotent_and_records_setpoint(tiny_run_state, tiny_loaded_client):
    proposal = _proposals(tiny_loaded_client)[0]

    first = tiny_loaded_client.post(
        f"/api/act/proposals/{proposal['proposal_id']}/approve",
        json={"approver_id": "sup-1"},
    )
    second = tiny_loaded_client.post(
        f"/api/act/proposals/{proposal['proposal_id']}/approve",
        json={"approver_id": "sup-2"},
    )

    assert first.status_code == 200 and second.status_code == 200
    # Re-approval returns the original record and appends nothing new.
    assert second.json() == first.json()
    matching = [
        r
        for r in tiny_run_state.audit_ledger.all_records()
        if r.proposal_id == proposal["proposal_id"]
    ]
    assert len(matching) == 1
    # The approved value became the parameter's known setpoint.
    key = (proposal["station_id"], proposal["parameter_name"])
    assert tiny_run_state.act_setpoints[key] == proposal["proposed_value"]


def test_next_proposal_generation_starts_from_approved_setpoint(
    tiny_run_state, tiny_loaded_client, tiny_run_id
):
    proposal = _proposals(tiny_loaded_client)[0]
    approved = tiny_loaded_client.post(
        f"/api/act/proposals/{proposal['proposal_id']}/approve",
        json={"approver_id": "sup-1"},
    )
    assert approved.status_code == 200

    # A fresh 'load' clears the proposal cache (but not setpoints);
    # regeneration must now move from the approved value, not the nominal
    # midpoint.
    reload = tiny_loaded_client.post(
        "/api/replay/control", json={"action": "load", "run_id": tiny_run_id}
    )
    assert reload.status_code == 200
    regenerated = _proposals(tiny_loaded_client)

    successor = next(
        (
            p
            for p in regenerated
            if p["station_id"] == proposal["station_id"]
            and p["parameter_name"] == proposal["parameter_name"]
        ),
        None,
    )
    assert successor is not None
    assert successor["current_value"] == proposal["proposed_value"]


def test_simulate_returns_projection_for_known_proposal(tiny_loaded_client):
    proposal = _proposals(tiny_loaded_client)[0]
    response = tiny_loaded_client.post(
        f"/api/act/proposals/{proposal['proposal_id']}/simulate"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal_id"] == proposal["proposal_id"]
    assert body["station_id"] == proposal["station_id"]
    assert body["parameter_name"] == proposal["parameter_name"]
    assert body["ci_low"] <= body["predicted_defect_rate_delta"] <= body["ci_high"]


def test_simulate_unknown_proposal_returns_not_found(tiny_loaded_client):
    _proposals(tiny_loaded_client)
    response = tiny_loaded_client.post("/api/act/proposals/not-a-real-id/simulate")
    assert response.status_code == 404
