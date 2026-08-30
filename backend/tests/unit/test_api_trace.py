"""Tests for lineage.api.routes.trace: the car trace query endpoint."""

from fastapi.testclient import TestClient

from lineage.api.app import create_app


def test_trace_without_run_loaded_returns_conflict(tiny_run_state):
    with TestClient(create_app()) as client:
        response = client.get("/api/trace/CAR-00000")
    assert response.status_code == 409


def test_trace_unknown_car_returns_not_found(tiny_loaded_client):
    response = tiny_loaded_client.get("/api/trace/CAR-99999")
    assert response.status_code == 404


def test_trace_returns_full_shape_and_excludes_flagged_car_from_cohort(tiny_loaded_client):
    response = tiny_loaded_client.get("/api/trace/CAR-00000")
    assert response.status_code == 200
    body = response.json()

    assert body["flagged_car_id"] == "CAR-00000"
    assert isinstance(body["originating_is_verifiable"], bool)
    assert body["contributions"], "every visited upstream station must be scored"
    for contribution in body["contributions"]:
        assert set(contribution) == {"station_id", "score", "deviation_z", "is_verifiable"}
    cohort_ids = {c["car_id"] for c in body["exposed_cohort"]}
    assert "CAR-00000" not in cohort_ids


def test_trace_with_station_the_car_never_visited_returns_not_found(tiny_loaded_client):
    response = tiny_loaded_client.get("/api/trace/CAR-00000", params={"station_id": "ST-99"})
    assert response.status_code == 404
