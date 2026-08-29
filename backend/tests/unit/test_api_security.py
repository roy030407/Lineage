"""Auth gating and resource guards.

The gate is deliberately inert without LINEAGE_API_KEY so that every
existing test, scripts/demo.py, and the Playwright harness keep working
unchanged. It engages only where the variable is set, which is deployment.

Reads and the WebSocket stay public so the Mirror and the role views work
without a credential; only writes and the two genuinely expensive reads
are gated. A shared secret compiled into the Vite bundle would be readable
in devtools, so the frontend prompts an operator for this value instead.
"""

from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state
from lineage.api.security import SIMULATE_SINGLE_FLIGHT, RateLimiter, SingleFlight


def _client(tmp_path, line) -> TestClient:
    reset_app_state(AppState(line=line, runs_root=tmp_path / "runs"))
    return TestClient(create_app())


def test_gate_is_inert_when_no_key_is_configured(tmp_path, tiny_line, monkeypatch):
    monkeypatch.delenv("LINEAGE_API_KEY", raising=False)
    with _client(tmp_path, tiny_line) as client:
        response = client.post("/api/builder/draft/start")
    assert response.status_code == 200


def test_mutating_request_without_the_key_is_rejected(tmp_path, tiny_line, monkeypatch):
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        response = client.post("/api/builder/draft/start")
    assert response.status_code == 401


def test_mutating_request_with_the_key_is_allowed(tmp_path, tiny_line, monkeypatch):
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        response = client.post("/api/builder/draft/start", headers={"X-Lineage-Key": "s3cret"})
    assert response.status_code == 200


def test_a_wrong_key_is_rejected(tmp_path, tiny_line, monkeypatch):
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        response = client.post("/api/builder/draft/start", headers={"X-Lineage-Key": "wrong"})
    assert response.status_code == 401


def test_reads_stay_public_even_with_a_key_configured(tmp_path, tiny_line, monkeypatch):
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        assert client.get("/api/line").status_code == 200
        assert client.get("/api/runs").status_code == 200


def test_expensive_read_is_gated_even_though_it_is_a_get(tmp_path, tiny_line, monkeypatch):
    """/api/predict/metrics is a documented ~105s job on first use. 'GETs
    are cheap' is an assumption this endpoint breaks, so it is gated by
    path rather than by method."""
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        response = client.get("/api/predict/metrics")
    assert response.status_code == 401


def test_delete_is_gated_too(tmp_path, tiny_line, monkeypatch):
    """Method-based gating has to cover every non-safe verb, not just POST.
    A per-route dependency list is exactly what would have missed this."""
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        response = client.delete("/api/floor_supervisor/assignments/ST-01")
    assert response.status_code == 401


def test_simulate_refuses_a_second_concurrent_run(tmp_path, tiny_line, monkeypatch):
    """Generation is ~11s of real CPU on a deployment pinned to one worker
    (see render.yaml), so two in flight is how a single client wedges the
    service. The lock is held directly rather than racing two real
    generations, which keeps the test deterministic and fast while still
    exercising the endpoint's own guard.
    """
    monkeypatch.delenv("LINEAGE_API_KEY", raising=False)
    assert SIMULATE_SINGLE_FLIGHT.acquire()
    try:
        with _client(tmp_path, tiny_line) as client:
            response = client.post("/api/datagen/simulate")
    finally:
        SIMULATE_SINGLE_FLIGHT.release()

    assert response.status_code == 429


def test_single_flight_admits_one_holder_at_a_time():
    flight = SingleFlight()
    assert flight.acquire()
    assert not flight.acquire()
    flight.release()
    assert flight.acquire()
    flight.release()


def test_rate_limiter_allows_up_to_capacity_then_refuses():
    limiter = RateLimiter(capacity=3, refill_per_second=0.0)
    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]


def test_rate_limiter_buckets_are_per_key():
    limiter = RateLimiter(capacity=1, refill_per_second=0.0)
    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")
