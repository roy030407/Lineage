"""Boot behaviour: the Mirror must open on a live line, not an empty canvas.

Every assertion here is about what a client observes with ZERO replay
control calls, because that is the exact scenario the existing e2e harness
could not see: frontend/e2e/global-setup.ts issues load/set_speed/play
before every Playwright run, which primed away a four-link failure chain.
"""

import threading
import time

from fastapi.testclient import TestClient

from lineage.api.app import DEFAULT_RUN_ID, create_app
from lineage.api.deps import AppState, get_app_state, reset_app_state
from lineage.datagen.models import RunConfig
from lineage.datagen.run import generate_run
from lineage.replay.models import LineState, PlaybackMode
from lineage.replay.ws import ConnectionManager


def _runs_root_with(tmp_path, line, run_id: str):
    config = RunConfig(
        run_id=run_id,
        random_seed=1,
        num_cars=3,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[],
        operator_shift_schedule=[],
    )
    runs_root = tmp_path / "runs"
    generate_run(line, config, output_root=runs_root)
    return runs_root


def _first_frame_or_none(client: TestClient, timeout_s: float = 8.0) -> dict | None:
    """Read the first WebSocket frame, giving up after `timeout_s`.

    Deliberately not a bare `receive_json()`. When no frame is ever sent
    (precisely the bug these tests exist for) that call blocks forever, so
    a broken build would wedge the whole suite instead of reporting a
    failure. The reader runs on a daemon thread so an abandoned one can
    never hold up interpreter exit either.
    """
    captured: dict[str, object] = {}

    def read() -> None:
        try:
            with client.websocket_connect("/ws/line") as websocket:
                captured["frame"] = websocket.receive_json()
        except Exception as exc:  # noqa: BLE001 - reported via the assertion below
            captured["error"] = exc

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout_s)
    frame = captured.get("frame")
    return frame if isinstance(frame, dict) else None


def test_boot_autoloads_default_run_and_streams_without_any_control_call(tmp_path, tiny_line):
    runs_root = _runs_root_with(tmp_path, tiny_line, DEFAULT_RUN_ID)
    reset_app_state(
        AppState(line=tiny_line, runs_root=runs_root, autoload_default_run=True)
    )

    with TestClient(create_app()) as client:
        # Checked before touching the socket so a missing autoload fails
        # here, fast and legibly, rather than as a socket timeout.
        assert get_app_state().engine is not None, "boot did not load the default run"
        frame = _first_frame_or_none(client)

    assert frame is not None, "no WebSocket frame arrived on connect"
    assert frame["run_id"] == DEFAULT_RUN_ID
    assert frame["playback_mode"] == "playing"
    assert len(frame["stations"]) == len(tiny_line.stations)


def test_websocket_sends_a_frame_on_connect_even_while_paused(tmp_path, tiny_line):
    """The tick loop broadcasts only while PLAYING, so a paused engine is
    the only way to prove the connect-time frame is real and not just the
    next scheduled tick arriving a moment later.
    """
    runs_root = _runs_root_with(tmp_path, tiny_line, DEFAULT_RUN_ID)
    reset_app_state(
        AppState(line=tiny_line, runs_root=runs_root, autoload_default_run=True)
    )

    with TestClient(create_app()) as client:
        assert client.post("/api/replay/control", json={"action": "pause"}).status_code == 200
        frame = _first_frame_or_none(client)

    assert frame is not None, "a paused engine sent nothing on connect"
    assert frame["playback_mode"] == "paused"


def test_a_substituted_app_state_never_autoloads(tiny_line):
    """The guard that keeps 26 existing tests green, and the reason the
    autoload_default_run flag exists at all.

    A first attempt guarded only on "does the default run exist in
    state.runs_root". That is the wrong question. tests/unit/
    test_api_builder.py builds AppState with a substituted `line` but
    leaves runs_root at the real RUNS_ROOT, which does contain the
    committed 42-station default_400_car_run. The autoload fired, tried to
    build a genealogy store for a 42-station run against a 3-station line,
    and died with KeyError: 'ST-04' across 26 tests.

    Existence of a run says nothing about whether it matches the loaded
    line. Any state constructed directly is by definition not the shipped
    configuration, so it never autoloads, whatever its runs_root holds.
    """
    reset_app_state(AppState(line=tiny_line))  # note: real RUNS_ROOT, flag defaulted

    with TestClient(create_app()) as client:
        response = client.post("/api/replay/control", json={"action": "pause"})

    assert response.status_code == 409


def test_autoload_is_skipped_when_the_default_run_is_absent(tmp_path, tiny_line):
    """Defence in depth behind the flag: even in the shipped configuration,
    a missing default run must leave the engine unloaded rather than raise
    during lifespan and take the whole app down at boot.
    """
    runs_root = _runs_root_with(tmp_path, tiny_line, "some-other-run")
    reset_app_state(
        AppState(line=tiny_line, runs_root=runs_root, autoload_default_run=True)
    )

    with TestClient(create_app()) as client:
        response = client.post("/api/replay/control", json={"action": "pause"})

    assert response.status_code == 409


class _RecordingConnectionManager(ConnectionManager):
    """Records what the background tick loop broadcasts.

    Used instead of a real WebSocket because the failure being guarded
    against is "nothing is ever sent", and a socket reader blocked forever
    on receive_json wedges TestClient shutdown rather than failing. This
    observes the loop's actual decision directly and cannot hang.
    """

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[LineState] = []

    async def broadcast(self, state: LineState) -> None:
        self.sent.append(state)
        await super().broadcast(state)


def test_the_tick_loop_keeps_broadcasting_while_paused(tmp_path, tiny_line):
    """The loop used to `continue` on PAUSED, broadcasting nothing at all.

    Nothing else tells a connected client that playback stopped:
    replay_control answers only the caller that posted it, and a stopped
    clock produces no further ticks. So a client's playback_mode stayed
    "playing" forever after a pause, its Play button never re-enabled, and
    the replay could not be resumed from the UI. Verified against a live
    backend before the fix: after draining the connect backlog, a paused
    client received no further frames whatsoever.

    Also asserts the clock does NOT advance while paused, so this can
    never be "fixed" by simply resuming playback.
    """
    runs_root = _runs_root_with(tmp_path, tiny_line, DEFAULT_RUN_ID)
    reset_app_state(
        AppState(line=tiny_line, runs_root=runs_root, autoload_default_run=True)
    )
    recorder = _RecordingConnectionManager()
    get_app_state().connection_manager = recorder

    with TestClient(create_app()) as client:
        assert client.post("/api/replay/control", json={"action": "pause"}).status_code == 200
        recorder.sent.clear()
        # The loop runs once per real second; this spans a few iterations.
        time.sleep(3.0)
        paused_frames = [f for f in recorder.sent if f.playback_mode == PlaybackMode.PAUSED]

    assert paused_frames, "the tick loop broadcast nothing at all while paused"
    timestamps = {f.timestamp for f in paused_frames}
    assert len(timestamps) == 1, "a paused clock must not advance between broadcasts"
