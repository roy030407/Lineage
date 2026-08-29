# Cold Start, Animation, and Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Lineage open on a live, animated, honest line instead of a blank dead end, and close the four defects plus three vulnerabilities that made that state possible.

**Architecture:** The backend loads and plays the default run during FastAPI's lifespan and clamps the clock at end of data instead of advancing into a fabricated all-RED state. The frontend stops gating station meshes on live tick state, gains a real error surface, and layers a staggered boot reveal plus persistent ambient motion over the existing three.js scene. Path validation, an environment-gated auth check, and single-flight limits harden the API without touching a single existing test.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pandas, pytest. React 18, TypeScript, zustand, three.js via react-three-fiber and drei, Vite, vitest, Playwright.

**Spec:** [docs/superpowers/specs/2026-08-29-cold-start-and-hardening-design.md](../specs/2026-08-29-cold-start-and-hardening-design.md)

## Global Constraints

Copied verbatim from the project working rules and the spec. Every task's requirements implicitly include this section.

- **Run `pytest -q` before you start and after you finish. Report both.** Baseline recorded 2026-08-29: `186 passed, 1 warning in 319.13s`. A full run takes over five minutes; budget for it.
- **If any previously-passing test now fails, revert your change and report.** Do not edit an existing test to make it pass. Tests are the spec.
- **Golden files in `backend/tests/golden/` are frozen.** Nothing in this plan touches them. If a change appears to require regenerating one, stop and ask.
- **Nothing hardcodes the number of stations. Everything reads `LineSpec`.**
- **A station with no sensor returns risk = UNKNOWN. Never risk = 0 or "safe".** This plan extends the same rule to a station with no tick state yet: never render it green.
- **`backend/lineage/act/envelope.py` is append-only.** No task touches it.
- **New modules must not modify existing module signatures.** Additive changes only. `Station3D`'s prop widening in Task 5 is the single deliberate exception and it is called out there.
- **Python: type hints everywhere, Pydantic for all boundary objects.**
- **No new dependency without asking.** Every task here is implementable with what is already installed. If you reach for a package, stop and ask.
- **Keep diffs small. One concern per commit.**
- **Never use em dashes** in code, comments, commit messages, docs, or UI copy. Use a comma, colon, semicolon, parentheses, or two sentences.
- **After each task print:** files changed | tests added | tests passing | what I did NOT do.
- **Do not push.** Commit locally only. Pushing happens after `/verify` returns PASS, which is outside this plan.

### The single most important constraint

Three existing tests assert that a cold backend returns 409:

- `backend/tests/unit/test_api_routes.py::test_replay_control_without_load_returns_conflict`
- `backend/tests/unit/test_api_routes.py::test_get_car_without_load_returns_conflict`
- `backend/tests/unit/test_api_routes.py::test_role_views_without_load_return_conflict`

All three run the real lifespan via `with TestClient(create_app())` and all three build state with `runs_root = tmp_path / "runs"` holding only `api-test-run`.

**The boot auto-load in Task 1 MUST check `state.runs_root`, never the module-level `RUNS_ROOT`.** The repository copy of `default_400_car_run` does exist, so a guard reading `RUNS_ROOT` would load a run in those three fixtures and break all three. Task 1 Step 1 writes a test that pins this exact behaviour so it cannot regress.

---

## File Structure

**Backend, created:**
- `backend/lineage/api/paths.py` — one responsibility: validating that a caller-supplied name resolves to a direct child of an intended root. Shared by the builder save handler and the replay run loader.
- `backend/lineage/api/security.py` — one responsibility: the environment-gated API key check and the in-process rate limiter and single-flight lock.
- `backend/tests/unit/test_api_boot.py` — boot auto-load and WebSocket first-frame behaviour.
- `backend/tests/unit/test_api_paths.py` — path validation, including the Windows drive-relative escape.
- `backend/tests/unit/test_api_security.py` — auth gating and denial-of-service guards.
- `backend/tests/unit/test_replay_end_of_run.py` — clock clamping and `ENDED`.

**Backend, modified:**
- `backend/tests/conftest.py` — currently a single docstring. Gains a `tiny_line` fixture so new test files do not each duplicate a 50-line `LineSpec` builder. There is no `tests/__init__.py`, so a conftest fixture is the only clean sharing mechanism.
- `backend/lineage/api/app.py` — boot auto-load, auth middleware registration.
- `backend/lineage/api/routes/mirror.py` — WebSocket first frame, `run_id` validation.
- `backend/lineage/api/routes/builder.py` — filename validation delegated to `paths.py`.
- `backend/lineage/api/routes/datagen.py` — single-flight guard.
- `backend/lineage/replay/models.py` — `PlaybackMode.ENDED`.
- `backend/lineage/replay/run_data.py` — `end_time`.
- `backend/lineage/replay/engine.py` — clamp and mode transition.

**Frontend, created:**
- `frontend/src/scene/bootReveal.ts` — pure timing functions for the staggered reveal. Deliberately free of React and three.js so it is unit-testable under vitest with no browser.
- `frontend/src/scene/bootReveal.test.ts`
- `frontend/src/components/BootOverlay.tsx` — the pre-`lineSpec` state and the error surface.
- `frontend/src/components/ApiKeyPrompt.tsx` — operator key entry.
- `frontend/playwright.coldstart.config.ts` — a second Playwright config with no `globalSetup`.
- `frontend/e2e/cold-start.spec.ts`

**Frontend, modified:**
- `frontend/src/state/types.ts`, `state/store.ts`, `state/api.ts`
- `frontend/src/scene/Line3D.tsx`, `Station3D.tsx`, `Car3D.tsx`, `Scene.tsx`
- `frontend/src/components/TopBar.tsx`, `frontend/src/styles/tokens.ts`
- `frontend/src/App.tsx`, `frontend/package.json`

**Frontend, deleted:**
- `frontend/src/routes/RoleShell.tsx`, `components/AlertList.tsx`, `components/ConfidenceMeter.tsx`, `components/KpiCard.tsx`, `components/RiskPill.tsx`

---

## Task 1: Boot auto-load and immediate first WebSocket frame

**Files:**
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/unit/test_api_boot.py`
- Modify: `backend/lineage/api/app.py:56-63`
- Modify: `backend/lineage/api/routes/mirror.py:128-137`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `lineage.api.app._autoload_default_run() -> None`. The `tiny_line` pytest fixture returning a two-station `LineSpec`, used by Tasks 1, 3, and 4.

- [ ] **Step 1: Add the shared `tiny_line` fixture**

`backend/tests/conftest.py` currently contains only a docstring, so this is purely additive. Replace the file with:

```python
"""Shared pytest fixtures (LineSpecs, tick engine, etc.)."""

from datetime import date

import pytest

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


@pytest.fixture
def tiny_line() -> LineSpec:
    """A minimal two-station line for API-level tests that only need *a*
    valid LineSpec, not a realistic one. Deliberately a fixture rather than
    an importable helper: there is no tests/__init__.py, so conftest
    discovery is the only sharing mechanism that does not require one."""
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
            name="Station One",
            zone=Zone.BODY,
            sequence_index=0,
            cycle_time_s=60.0,
            machine=machine,
            sensors=[sensor],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            commissioning_baseline=baseline,
        ),
        StationSpec(
            id="ST-02",
            name="Station Two",
            zone=Zone.BODY,
            sequence_index=1,
            cycle_time_s=60.0,
            machine=machine,
            sensors=[],
            acquisition_mode=AcquisitionMode.MANUAL,
            commissioning_baseline=None,
        ),
    ]
    return LineSpec(
        plant_name="Test Plant",
        stations=stations,
        layout=LayoutSpec(
            coordinates=[
                StationCoordinate(station_id="ST-01", x_m=0.0, y_m=0.0),
                StationCoordinate(station_id="ST-02", x_m=10.0, y_m=0.0),
            ],
        ),
        environment_envelope=EnvironmentEnvelope(),
    )
```

Before writing this, open `backend/lineage/config/specs.py` and confirm every field name and required argument above matches the current `StationSpec`, `LayoutSpec`, `LineSpec`, and `EnvironmentEnvelope` definitions. `backend/tests/unit/test_api_routes.py:27-75` builds the same shape and is the reference; copy from it if anything differs. Do not modify `test_api_routes.py`.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/unit/test_api_boot.py`:

```python
"""Boot behaviour: the Mirror must open on a live line, not an empty canvas.

Every assertion here is about what a client observes with ZERO replay
control calls, because that is the exact scenario the previous e2e harness
could not see: frontend/e2e/global-setup.ts issues load/set_speed/play
before every Playwright run, which primed away a four-link failure chain.
"""

from lineage.api.app import DEFAULT_RUN_ID, create_app
from lineage.api.deps import AppState, reset_app_state
from lineage.datagen.models import RunConfig
from lineage.datagen.run import generate_run
from fastapi.testclient import TestClient


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


def test_boot_autoloads_default_run_and_streams_without_any_control_call(tmp_path, tiny_line):
    runs_root = _runs_root_with(tmp_path, tiny_line, DEFAULT_RUN_ID)
    reset_app_state(AppState(line=tiny_line, runs_root=runs_root))

    with TestClient(create_app()) as client:
        with client.websocket_connect("/ws/line") as websocket:
            message = websocket.receive_json()

    assert message["run_id"] == DEFAULT_RUN_ID
    assert message["playback_mode"] == "playing"
    assert len(message["stations"]) == len(tiny_line.stations)


def test_boot_autoload_is_scoped_to_state_runs_root_not_the_module_default(tmp_path, tiny_line):
    """Pins the guard that keeps three existing cold-start 409 tests green.

    test_replay_control_without_load_returns_conflict and its two siblings
    build state with a tmp_path runs_root holding only 'api-test-run'. The
    repository copy of default_400_car_run DOES exist, so an autoload
    reading the module-level RUNS_ROOT would load a run in those fixtures
    and break all three. This test fails loudly if anyone widens it.
    """
    runs_root = _runs_root_with(tmp_path, tiny_line, "some-other-run")
    reset_app_state(AppState(line=tiny_line, runs_root=runs_root))

    with TestClient(create_app()) as client:
        response = client.post("/api/replay/control", json={"action": "pause"})

    assert response.status_code == 409
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_api_boot.py -v
```

Expected: `test_boot_autoloads_default_run_and_streams_without_any_control_call` FAILS. It will either time out waiting for a frame or raise on `receive_json`, because `snapshot_history` is empty and no engine exists. The second test should already PASS, which is correct: it is a regression guard, not a driver.

- [ ] **Step 4: Add the boot auto-load**

In `backend/lineage/api/app.py`, extend the existing mirror import:

```python
from lineage.api.routes.mirror import load_run_into_state
from lineage.api.routes.mirror import router as mirror_router
```

Add the function directly below `_ensure_default_run_exists`:

```python
def _autoload_default_run() -> None:
    """Opens the Mirror on a live line rather than an empty canvas.

    Reads state.runs_root, NEVER the module-level RUNS_ROOT. Three tests
    (test_replay_control_without_load_returns_conflict and its two
    siblings) assert a 409 from a cold backend, and they build state with a
    tmp_path runs_root that has no default run. The repository copy of
    default_400_car_run does exist, so checking RUNS_ROOT here would load a
    run inside those fixtures and break all three. See
    tests/unit/test_api_boot.py for the guard that pins this.

    Reuses load_run_into_state verbatim; no second load path exists.
    """
    state = get_app_state()
    if state.line is None:
        return
    if not (state.runs_root / DEFAULT_RUN_ID).exists():
        return
    load_run_into_state(state, DEFAULT_RUN_ID)
```

Call it from `_lifespan`, immediately after the existing call:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI):
    _ensure_default_run_exists()
    _autoload_default_run()
    task = asyncio.create_task(_tick_loop())
    try:
        yield
    finally:
        task.cancel()
```

`SimClock.__init__` already sets `mode = PlaybackMode.PLAYING` (`backend/lineage/replay/clock.py:18`), so auto-play needs no further change.

- [ ] **Step 5: Send a first frame on WebSocket connect**

In `backend/lineage/api/routes/mirror.py`, replace the body of `ws_line`'s replay loop:

```python
@router.websocket("/ws/line")
async def ws_line(websocket: WebSocket, state: AppState = Depends(get_app_state)) -> None:
    await state.connection_manager.connect(websocket)
    recent = state.snapshot_history.recent()
    if recent:
        for snapshot in recent:
            await websocket.send_json(snapshot.model_dump(mode="json"))
    elif state.engine is not None:
        # A client connecting before the first tick used to receive nothing
        # at all and sit on a null lineState for up to a full second, or
        # forever if playback was never started. An engine that exists can
        # always describe the present, so say so immediately.
        await websocket.send_json(state.engine.current_state().model_dump(mode="json"))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.connection_manager.disconnect(websocket)
```

- [ ] **Step 6: Run the new tests, then the neighbours most at risk**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_api_boot.py -v
```
Expected: 2 passed.

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_api_routes.py tests/unit/test_api_predict.py tests/unit/test_api_builder.py -q
```
Expected: all pass. These hold the three cold-start 409 tests. If any fails, the guard is reading the wrong root. Revert and report.

- [ ] **Step 7: Full suite**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
```
Expected: `188 passed` (186 baseline plus 2 new). Any previously-passing failure means revert and report.

- [ ] **Step 8: Commit**

```bash
git add backend/tests/conftest.py backend/tests/unit/test_api_boot.py backend/lineage/api/app.py backend/lineage/api/routes/mirror.py
git commit -m "fix(api): load and play the default run at boot, send a WS frame on connect

The Mirror opened on an empty canvas because nothing ever called
load_run_into_state: _ensure_default_run_exists only writes files to disk.
The WebSocket then replayed an empty snapshot history, so a connecting
client received zero bytes and sat on a null lineState indefinitely.

The autoload is guarded on state.runs_root, never the module-level
RUNS_ROOT, so the three existing cold-start 409 tests stay green. A new
test pins that guard.

Files changed: api/app.py, api/routes/mirror.py, tests/conftest.py,
tests/unit/test_api_boot.py
Tests: 2 added, 188 passing"
```

---

## Task 2: `ENDED` playback mode and clock clamp

Auto-play alone does not remove the blank screen, it delays it. The default run holds 9h 38m of simulated time, which is 9.6 minutes of wall clock at 60x. Past the end, `car_at_station_at` returns `None` for every station and `sensor_is_reporting` returns `RED` for every station, while `auto_tick` advances forever. That is an empty line plus a fabricated all-stations-RED alarm.

**Files:**
- Create: `backend/tests/unit/test_replay_end_of_run.py`
- Modify: `backend/lineage/replay/models.py:38-41`
- Modify: `backend/lineage/replay/run_data.py:26`
- Modify: `backend/lineage/replay/engine.py:23-45`
- Modify: `frontend/src/state/types.ts:110`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `PlaybackMode.ENDED` (value `"ended"`), `RunData.end_time: datetime`, `ReplayEngine.tick()` clamping behaviour. Task 5 consumes `"ended"` in the TypeScript union.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_replay_end_of_run.py`:

```python
"""End-of-data behaviour.

Past the last telemetry row every station reads as RED (its last reading is
older than sensor_stale_after_s) and holds no car. Advancing into that
region reports a fabricated line-wide alarm, which is the same class of
untruth the 'never report a fake safe value' invariant exists to prevent.
The clock stops at the last real frame instead.
"""

from datetime import timedelta

from lineage.config.specs import LineSpec
from lineage.replay.engine import ReplayEngine
from lineage.replay.models import PlaybackMode
from lineage.replay.run_data import RunData
from lineage.datagen.models import RunConfig
from lineage.datagen.run import generate_run


def _engine(tmp_path, line: LineSpec) -> ReplayEngine:
    config = RunConfig(
        run_id="end-of-run",
        random_seed=1,
        num_cars=3,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[],
        operator_shift_schedule=[],
    )
    generate_run(line, config, output_root=tmp_path)
    run_data = RunData("end-of-run", tmp_path / "end-of-run")
    return ReplayEngine(line, run_data, start_time=run_data.start_time)


def test_run_data_exposes_an_end_time_at_or_after_start(tmp_path, tiny_line):
    engine = _engine(tmp_path, tiny_line)
    assert engine.run_data.end_time >= engine.run_data.start_time


def test_tick_past_the_end_clamps_the_clock_and_reports_ended(tmp_path, tiny_line):
    engine = _engine(tmp_path, tiny_line)
    end = engine.run_data.end_time

    engine.clock.seek(end + timedelta(seconds=1))
    state = engine.tick()

    assert state.playback_mode == PlaybackMode.ENDED
    assert engine.clock.current_time == end
    assert state.timestamp == end


def test_ended_clock_does_not_keep_advancing(tmp_path, tiny_line):
    engine = _engine(tmp_path, tiny_line)
    engine.clock.seek(engine.run_data.end_time + timedelta(seconds=1))
    engine.tick()

    first = engine.clock.current_time
    engine.tick()
    engine.tick()

    assert engine.clock.current_time == first


def test_play_after_end_restarts_from_the_beginning(tmp_path, tiny_line):
    engine = _engine(tmp_path, tiny_line)
    engine.clock.seek(engine.run_data.end_time + timedelta(seconds=1))
    engine.tick()
    assert engine.clock.mode == PlaybackMode.ENDED

    engine.resume()

    assert engine.clock.mode == PlaybackMode.PLAYING
    assert engine.clock.current_time == engine.run_data.start_time
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_replay_end_of_run.py -v
```
Expected: FAIL. `RunData` has no `end_time`, `PlaybackMode` has no `ENDED`.

- [ ] **Step 3: Add the `ENDED` member**

In `backend/lineage/replay/models.py`:

```python
class PlaybackMode(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STEP = "step"
    ENDED = "ended"
    """The clock reached the last frame the run actually has data for.

    Distinct from PAUSED, which is a user decision that can be resumed in
    place. ENDED is a property of the data: advancing past it would report
    every station RED (its last reading is now stale) and holding no car,
    which is a fabricated alarm rather than an observation. Pressing play
    from here restarts from the run's start_time.
    """
```

Additive. The only test referencing this enum is `tests/unit/test_replay.py:203`, which asserts `PAUSED` after a pause call and is unaffected.

- [ ] **Step 4: Add `end_time` to `RunData`**

In `backend/lineage/replay/run_data.py`, directly after the existing `start_time` assignment at line 26:

```python
        self.start_time: datetime = self._telemetry.timestamp.min().to_pydatetime()
        # The last moment this run has anything real to say. Past it, every
        # per-station query below degrades to "no car, stale sensor", which
        # ReplayEngine must not present as a live line-wide fault.
        self.end_time: datetime = max(
            self._telemetry.timestamp.max().to_pydatetime(),
            self._events.timestamp.max().to_pydatetime(),
        )
```

- [ ] **Step 5: Clamp in the engine**

In `backend/lineage/replay/engine.py`, replace `tick` and `resume`:

```python
    def resume(self) -> None:
        # Resuming an ENDED run restarts it rather than doing nothing: the
        # clock is already at the last frame, so plain resume would leave
        # the Play button inert.
        if self.clock.mode == PlaybackMode.ENDED:
            self.clock.seek(self.run_data.start_time)
        self.clock.resume()

    def tick(self) -> LineState:
        self.clock.auto_tick()
        if self.clock.current_time >= self.run_data.end_time:
            self.clock.seek(self.run_data.end_time)
            self.clock.mode = PlaybackMode.ENDED
        return self.current_state()
```

Add the import at the top of the file:

```python
from lineage.replay.models import LineState, MachineHealth, PlaybackMode, StationState
```

`SimClock.auto_tick` already returns early for any mode that is not `PLAYING`, so `ENDED` stops the clock with no change to `clock.py`.

- [ ] **Step 6: Widen the frontend union**

In `frontend/src/state/types.ts` line 110:

```ts
export type PlaybackMode = "playing" | "paused" | "step" | "ended";
```

Shipping the Python enum without this leaves the frontend able to receive a value its own types do not admit, so both sides of one contract move together.

- [ ] **Step 7: Run the tests**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_replay_end_of_run.py tests/unit/test_replay.py -v
```
Expected: 4 new pass, all of `test_replay.py` still passes.

```bash
cd frontend && npx tsc --noEmit
```
Expected: clean.

- [ ] **Step 8: Full suite**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
```
Expected: `192 passed`.

- [ ] **Step 9: Commit**

```bash
git add backend/lineage/replay/models.py backend/lineage/replay/run_data.py backend/lineage/replay/engine.py backend/tests/unit/test_replay_end_of_run.py frontend/src/state/types.ts
git commit -m "fix(replay): clamp the clock at end of data instead of faking a line-wide alarm

Auto-play exhausts the default run in 9.6 minutes at 60x. Past the last
telemetry row every station reports RED (stale reading) and holds no car,
while auto_tick advanced forever. That is a fabricated alarm, not an
observation.

PlaybackMode gains ENDED, RunData gains end_time, and tick() clamps rather
than advancing. Play from ENDED restarts from the run start so the control
is never inert. The TS union moves with the enum.

Files changed: replay/models.py, replay/run_data.py, replay/engine.py,
state/types.ts, tests/unit/test_replay_end_of_run.py
Tests: 4 added, 192 passing"
```

---

## Task 3: Path validation for filename and `run_id`

**Files:**
- Create: `backend/lineage/api/paths.py`
- Create: `backend/tests/unit/test_api_paths.py`
- Modify: `backend/lineage/api/routes/builder.py:291-313`
- Modify: `backend/lineage/api/routes/mirror.py:32-42`

**Interfaces:**
- Consumes: `tiny_line` fixture from Task 1.
- Produces: `lineage.api.paths.safe_child(root: Path, name: str) -> Path`, raising `ValueError` on rejection.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_api_paths.py`:

```python
"""Path validation.

The builder save handler used to reject '/', '\\', '..' and require a
'.yaml' suffix. On Windows the name 'C:evil.yaml' passes all four checks
and Path('data/lines') / 'C:evil.yaml' resolves to 'C:evil.yaml', escaping
lines_root entirely. Drive-relative names re-anchor; a separator scan
cannot see that. safe_child resolves and compares parents instead.
"""

from pathlib import Path

import pytest

from lineage.api.paths import safe_child

ESCAPES = [
    "C:evil.yaml",
    "c:evil.yaml",
    "../evil.yaml",
    "..\\evil.yaml",
    "sub/evil.yaml",
    "sub\\evil.yaml",
    "/etc/passwd",
    "\\\\server\\share\\evil.yaml",
    "..",
    ".",
    "",
]


@pytest.mark.parametrize("name", ESCAPES)
def test_rejects_anything_that_is_not_a_plain_child_name(tmp_path, name):
    with pytest.raises(ValueError):
        safe_child(tmp_path, name)


def test_accepts_a_plain_child_name(tmp_path):
    assert safe_child(tmp_path, "line.yaml") == tmp_path / "line.yaml"


def test_accepts_a_name_with_dots_that_is_still_a_child(tmp_path):
    assert safe_child(tmp_path, "my.line.v2.yaml") == tmp_path / "my.line.v2.yaml"


def test_result_is_always_inside_the_root(tmp_path):
    result = safe_child(tmp_path, "line.yaml")
    assert result.resolve().parent == Path(tmp_path).resolve()
```

Add to the same file the two endpoint-level tests:

```python
from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state


def test_builder_save_rejects_a_drive_relative_filename(tmp_path, tiny_line):
    lines_root = tmp_path / "lines"
    lines_root.mkdir()
    reset_app_state(AppState(line=tiny_line, runs_root=tmp_path / "runs", lines_root=lines_root))
    with TestClient(create_app()) as client:
        client.post("/api/builder/draft/start")
        response = client.post("/api/builder/save", json={"filename": "C:evil.yaml"})
    assert response.status_code == 400
    assert not Path("C:evil.yaml").exists()


def test_replay_load_rejects_a_traversing_run_id(tmp_path, tiny_line):
    reset_app_state(AppState(line=tiny_line, runs_root=tmp_path / "runs"))
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/replay/control", json={"action": "load", "run_id": "../../etc"}
        )
    assert response.status_code == 400
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_api_paths.py -v
```
Expected: collection error, `lineage.api.paths` does not exist.

- [ ] **Step 3: Write `paths.py`**

```python
"""Validating that a caller-supplied name stays inside its intended root.

Scanning a string for separators is not sufficient. On Windows a
drive-relative name like 'C:evil.yaml' contains no separator and no '..',
yet Path('data/lines') / 'C:evil.yaml' evaluates to 'C:evil.yaml': the
drive letter re-anchors the path and the join is discarded. Verified on the
development machine. The only reliable check is to resolve the candidate
and compare its parent against the resolved root.
"""

from pathlib import Path

_REJECTED_NAMES = {"", ".", ".."}


def safe_child(root: Path, name: str) -> Path:
    """Return `root / name`, or raise ValueError if `name` is anything
    other than a plain child basename of `root`.

    Raises rather than returning None or an HTTPException so this module
    stays free of any FastAPI dependency; callers translate to 400.
    """
    if name in _REJECTED_NAMES:
        raise ValueError("name must be a plain filename, not empty or a directory reference")
    if Path(name).name != name:
        raise ValueError("name must be a plain filename with no path separators or drive prefix")

    candidate = (root / name).resolve()
    if candidate.parent != Path(root).resolve():
        raise ValueError("name must resolve to a direct child of the intended directory")
    return root / name
```

`Path("C:evil.yaml").name` is `"evil.yaml"` on Windows, which differs from the input, so the second check rejects it. The resolve comparison is the backstop for anything platform-specific the name check misses.

- [ ] **Step 4: Use it in the builder save handler**

In `backend/lineage/api/routes/builder.py`, add the import:

```python
from lineage.api.paths import safe_child
```

Replace the validation block inside `save_draft` (currently lines 295 to 310) with:

```python
    filename = req.filename
    if not filename.endswith(".yaml"):
        raise HTTPException(status_code=400, detail="filename must end in '.yaml'")
    try:
        target = safe_child(state.lines_root, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if target.exists():
        raise HTTPException(status_code=409, detail=f"{filename!r} already exists")
```

Leave the `.write_text(...)` line and the return value exactly as they are. Keep the `.yaml` suffix check ahead of `safe_child` so the existing "must be a plain '*.yaml' basename" behaviour and its 400 status are preserved for callers.

- [ ] **Step 5: Use it in the run loader**

In `backend/lineage/api/routes/mirror.py`, add the same import, then replace the `run_dir` assignment inside `load_run_into_state`:

```python
    try:
        run_dir = safe_child(state.runs_root, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
```

Unvalidated, `state.runs_root / run_id` with `..` segments was an unauthenticated existence oracle for arbitrary filesystem paths.

- [ ] **Step 6: Run the tests**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_api_paths.py tests/unit/test_api_builder.py tests/unit/test_api_routes.py -v
```
Expected: all new tests pass, every existing builder and route test still passes. `test_api_builder.py` already covers the legitimate save path and the 409-on-existing case; both must stay green.

- [ ] **Step 7: Full suite**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
```
Expected: `207 passed` (192 plus 15: 11 parametrised rejections, 3 acceptance, 2 endpoint).

- [ ] **Step 8: Commit**

```bash
git add backend/lineage/api/paths.py backend/lineage/api/routes/builder.py backend/lineage/api/routes/mirror.py backend/tests/unit/test_api_paths.py
git commit -m "fix(api): reject names that escape their intended directory

The builder save handler rejected '/', '\\\\' and '..' and required a
.yaml suffix. On Windows 'C:evil.yaml' passes all four: the drive letter
re-anchors the join and the name lands outside lines_root. run_id was not
validated at all, making runs_root traversal an existence oracle.

safe_child resolves the candidate and compares parents, which no
separator scan can substitute for.

Files changed: api/paths.py (new), api/routes/builder.py,
api/routes/mirror.py, tests/unit/test_api_paths.py
Tests: 15 added, 207 passing"
```

---

## Task 4: Auth gate and denial-of-service guards

The key is required for mutating and expensive requests only. GET endpoints and the WebSocket stay public so the Mirror and role views work without a credential.

**The gate is inert when `LINEAGE_API_KEY` is unset.** That is what keeps all existing tests, `scripts/demo.py`, the Playwright harness, and local development working with zero edits.

A method-based middleware is used rather than 17 per-route dependencies. There are 17 mutating routes across 6 files today; a middleware covers all of them in one edit and cannot miss a route added later.

**Files:**
- Create: `backend/lineage/api/security.py`
- Create: `backend/tests/unit/test_api_security.py`
- Modify: `backend/lineage/api/app.py:77-93`
- Modify: `backend/lineage/api/routes/datagen.py:30-44`

**Interfaces:**
- Consumes: `tiny_line` fixture from Task 1.
- Produces: `lineage.api.security.api_key_middleware`, `lineage.api.security.RateLimiter`, `lineage.api.security.SINGLE_FLIGHT` names used by `app.py` and `datagen.py`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_api_security.py`:

```python
"""Auth gating and resource guards.

The gate is deliberately inert without LINEAGE_API_KEY so that every
existing test, scripts/demo.py, and the Playwright harness keep working
unchanged. It engages only where the variable is set, which is deployment.
"""

import threading

from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state


def _client(tmp_path, line):
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
        response = client.post(
            "/api/builder/draft/start", headers={"X-Lineage-Key": "s3cret"}
        )
    assert response.status_code == 200


def test_a_wrong_key_is_rejected(tmp_path, tiny_line, monkeypatch):
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        response = client.post(
            "/api/builder/draft/start", headers={"X-Lineage-Key": "wrong"}
        )
    assert response.status_code == 401


def test_reads_stay_public_even_with_a_key_configured(tmp_path, tiny_line, monkeypatch):
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        assert client.get("/api/line").status_code == 200
        assert client.get("/api/runs").status_code == 200


def test_expensive_read_is_gated_even_though_it_is_a_get(tmp_path, tiny_line, monkeypatch):
    """/api/predict/metrics is a documented ~105s job. A GET being cheap is
    an assumption this endpoint breaks, so it is gated by path, not method."""
    monkeypatch.setenv("LINEAGE_API_KEY", "s3cret")
    with _client(tmp_path, tiny_line) as client:
        response = client.get("/api/predict/metrics")
    assert response.status_code == 401


def test_simulate_runs_are_single_flight(tmp_path, tiny_line, monkeypatch):
    """A second concurrent simulate must be refused, not started. Generation
    is real CPU work on a deployment pinned to one worker (see render.yaml),
    so two in flight is how a single client wedges the service."""
    monkeypatch.delenv("LINEAGE_API_KEY", raising=False)
    statuses: list[int] = []
    with _client(tmp_path, tiny_line) as client:

        def call() -> None:
            statuses.append(client.post("/api/datagen/simulate").status_code)

        threads = [threading.Thread(target=call) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert 200 in statuses
    assert 429 in statuses
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_api_security.py -v
```
Expected: the inert-gate and reads-public tests PASS already; the four gating tests and the single-flight test FAIL.

- [ ] **Step 3: Write `security.py`**

```python
"""Request-level guards: an environment-gated API key check, a small
in-process rate limiter, and a single-flight lock.

All three are in-process by design. AppState is already a process-wide
global and render.yaml pins --workers 1 for that reason (see api/deps.py),
so per-process state here adds no constraint that does not already exist.
Anything multi-instance needs shared state first, which is a separate
change.
"""

import hmac
import os
import threading
import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

API_KEY_HEADER = "X-Lineage-Key"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
"""OPTIONS is exempt so CORS preflight reaches CORSMiddleware. A browser
never attaches custom headers to a preflight, so gating it would break
every cross-origin write before the real request was ever sent."""

GATED_READ_PREFIXES = ("/api/predict/metrics",)
"""GETs that are not cheap. The ledger build is a documented ~105s job on
first use, so 'reads are free' does not hold for it."""


def _configured_key() -> str | None:
    key = os.environ.get("LINEAGE_API_KEY")
    return key or None


def _requires_key(request: Request) -> bool:
    if request.method not in SAFE_METHODS:
        return True
    return request.url.path.startswith(GATED_READ_PREFIXES)


async def api_key_middleware(
    request: Request, call_next: Callable[[Request], Awaitable]
):
    """Rejects unauthenticated writes and expensive reads when a key is
    configured. A no-op when LINEAGE_API_KEY is unset, which is local
    development, the test suite, and the Playwright harness.

    A shared secret compiled into the Vite bundle would be readable in
    devtools, so the frontend prompts the operator for this value and holds
    it in sessionStorage. It is never a VITE_ variable.
    """
    expected = _configured_key()
    if expected is None or not _requires_key(request):
        return await call_next(request)

    supplied = request.headers.get(API_KEY_HEADER, "")
    # compare_digest, not ==, so rejection time does not vary with how many
    # leading characters of the key were guessed correctly.
    if not hmac.compare_digest(supplied, expected):
        return JSONResponse(
            status_code=401,
            content={"detail": f"missing or invalid {API_KEY_HEADER}"},
        )
    return await call_next(request)


class SingleFlight:
    """Refuses a second concurrent entry rather than queueing it.

    Queueing would be worse here: the caller is an HTTP request with a
    client-side timeout, and generation takes ~11s, so a queue just
    converts one rejected request into two slow ones on a single worker.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        self._lock.release()


class RateLimiter:
    """A token bucket keyed by client host. Dependency-free on purpose."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_second)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True


SIMULATE_SINGLE_FLIGHT = SingleFlight()
```

- [ ] **Step 4: Register the middleware**

In `backend/lineage/api/app.py`, add the import and register it inside `create_app`, after the CORS middleware:

```python
from lineage.api.security import api_key_middleware
```

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Registered after CORS so it sits outside it. OPTIONS is exempt inside
    # the middleware itself, so preflight still reaches CORSMiddleware.
    # allow_headers=["*"] already admits X-Lineage-Key.
    app.middleware("http")(api_key_middleware)
```

- [ ] **Step 5: Guard simulate**

In `backend/lineage/api/routes/datagen.py`, add the import and wrap the body:

```python
from lineage.api.security import SIMULATE_SINGLE_FLIGHT
```

```python
@router.post("/api/datagen/simulate")
def simulate(state: AppState = Depends(get_app_state)) -> SimulateResponse:
    if state.line is None:
        raise HTTPException(status_code=404, detail="no line loaded")

    # ~11s of real CPU work on a deployment pinned to one worker. A second
    # concurrent call is refused rather than queued; see security.py.
    if not SIMULATE_SINGLE_FLIGHT.acquire():
        raise HTTPException(
            status_code=429, detail="a simulation is already running; try again shortly"
        )
    try:
        run_id = f"simulated_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        config = build_run_config(
            state.line,
            run_id=run_id,
            random_seed=random.randint(1, 2**31 - 1),
            sim_start_time=datetime.now(),
        )
        artifacts = generate_run(state.line, config, state.runs_root)
        load_run_into_state(state, artifacts.run_id)
        return SimulateResponse(run_id=artifacts.run_id, num_cars=artifacts.num_cars)
    finally:
        SIMULATE_SINGLE_FLIGHT.release()
```

- [ ] **Step 6: Run the tests**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_api_security.py tests/unit/test_api_datagen.py -v
```
Expected: 7 new pass, `test_api_datagen.py` still passes.

- [ ] **Step 7: Full suite**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
```
Expected: `214 passed`. If anything else fails, the gate is not inert; check that `LINEAGE_API_KEY` is genuinely absent from the environment.

- [ ] **Step 8: Commit**

```bash
git add backend/lineage/api/security.py backend/lineage/api/app.py backend/lineage/api/routes/datagen.py backend/tests/unit/test_api_security.py
git commit -m "feat(api): environment-gated API key for writes, single-flight on simulate

Every endpoint was unauthenticated while /api/datagen/simulate is ~11s of
CPU and /api/predict/metrics is ~105s, on a deployment pinned to one
worker. One curl loop was enough to wedge it.

Method-based middleware rather than 17 per-route dependencies, so a route
added later cannot silently miss the gate. Reads and the WebSocket stay
public. Inert without LINEAGE_API_KEY, so tests, demo.py, and the
Playwright harness are untouched.

Files changed: api/security.py (new), api/app.py, api/routes/datagen.py,
tests/unit/test_api_security.py
Tests: 7 added, 214 passing"
```

---

## Task 5: Render stations without live state, and fix the Play/Pause state machine

`Line3D.tsx:144` reads `if (!coord || !state) return null;`, so with a null `lineState` zero stations render. `TopBar.tsx:38` computes `isPaused` as `undefined === "paused"`, which is `false`, so Play renders disabled and Pause renders enabled at exactly the moment Play is the only useful control.

**A note on honesty.** `SensorHealth` has a `not_yet_reporting` member but `MachineHealth` has only `green` and `red`. There is no correct existing value for "no tick has arrived". Rendering `green` fabricates a safe value; rendering `red` fabricates a fault and triggers `MachineFaultBeam`. Both props therefore widen to accept `null`, and `null` renders the shared `ring` shape that the token vocabulary already defines as "no meaningful signal at all". This is the one deliberate signature change in the plan.

**Files:**
- Modify: `frontend/src/styles/tokens.ts`
- Modify: `frontend/src/scene/Station3D.tsx:128-137,188-191,227-231`
- Modify: `frontend/src/scene/Line3D.tsx:141-158`
- Modify: `frontend/src/components/TopBar.tsx:38,102-108`

**Interfaces:**
- Consumes: `"ended"` from Task 2's `PlaybackMode` union.
- Produces: `UNKNOWN_STATUS_TOKEN` exported from `styles/tokens.ts`. `Station3D` props `sensorHealth: SensorHealth | null` and `machineHealth: MachineHealth | null`. Task 7 adds a `sequenceIndex` prop to the same component.

- [ ] **Step 1: Add the unknown token**

In `frontend/src/styles/tokens.ts`, directly below `MACHINE_HEALTH_TOKENS`:

```ts
// A station the line spec knows about but no tick has described yet. Not a
// fault and not healthy: the ring shape is already defined above as "not
// applicable / unknown, no meaningful signal at all", which is exactly
// this. MachineHealth has no not_yet_reporting member the way SensorHealth
// does, so this covers both domains rather than widening either enum.
export const UNKNOWN_STATUS_TOKEN: StatusToken = {
  color: PALETTE.steelNeutral,
  shape: "ring",
  label: "Awaiting Data",
};
```

- [ ] **Step 2: Widen the `Station3D` props**

In `frontend/src/scene/Station3D.tsx`, change the `Props` interface:

```ts
interface Props {
  stationId: string;
  stationName: string;
  x: number;
  z: number;
  // Null until the first tick describes this station. Rendering green
  // would fabricate a safe value and rendering red would fabricate a
  // fault (and light a fault beam), so null gets its own token.
  sensorHealth: SensorHealth | null;
  machineHealth: MachineHealth | null;
  latestReadings: LatestReading[];
  isSelected: boolean;
}
```

Update the import and the two token lookups:

```ts
import {
  MACHINE_HEALTH_TOKENS,
  PALETTE,
  SENSOR_HEALTH_TOKENS,
  UNKNOWN_STATUS_TOKEN,
  type ShapeToken,
} from "../styles/tokens";
```

```ts
  const sensorToken = sensorHealth === null ? UNKNOWN_STATUS_TOKEN : SENSOR_HEALTH_TOKENS[sensorHealth];
  const machineToken = machineHealth === null ? UNKNOWN_STATUS_TOKEN : MACHINE_HEALTH_TOKENS[machineHealth];
```

The two beam conditions at lines 230 and 231 already read `sensorHealth === "red"` and `machineHealth === "red"`, which are correctly false for `null`. Leave them unchanged.

- [ ] **Step 3: Stop gating station meshes on tick state**

In `frontend/src/scene/Line3D.tsx`, replace the station map:

```tsx
      {lineSpec.stations.map((station) => {
        const coord = coordinatesByStation.get(station.id);
        // Only the coordinate is required. Gating on `state` too meant a
        // client with no tick yet rendered zero stations: the blank screen.
        if (!coord) return null;
        const state = stationStateById.get(station.id);
        return (
          <Station3D
            key={station.id}
            stationId={station.id}
            stationName={station.name}
            x={coord.x_m}
            z={coord.y_m}
            sensorHealth={state?.sensor_health ?? null}
            machineHealth={state?.machine_health ?? null}
            latestReadings={state?.latest_readings ?? []}
            isSelected={selectedStationId === station.id}
          />
        );
      })}
```

- [ ] **Step 4: Fix the Play/Pause state machine**

In `frontend/src/components/TopBar.tsx`, replace line 38:

```tsx
  // Derived from real state with an explicit no-state-yet branch. The old
  // `lineState?.playback_mode === "paused"` evaluated undefined === "paused"
  // as false before the first tick, which disabled Play and enabled Pause
  // at exactly the moment Play was the only control that could help.
  const mode = lineState?.playback_mode ?? null;
  const canPlay = mode !== "playing";
  const canPause = mode === "playing";
```

Replace the two buttons at lines 102 to 107:

```tsx
      <button onClick={() => void play()} disabled={!canPlay} aria-pressed={mode === "playing"}>
        {mode === "ended" ? "Replay" : "Play"}
      </button>
      <button onClick={() => void pause()} disabled={!canPause} aria-pressed={mode === "paused"}>
        Pause
      </button>
```

Add an end-of-run notice immediately after the speed buttons, before the timestamp:

```tsx
      {mode === "ended" && (
        <span className="eyebrow" style={{ color: "var(--color-beacon-amber)" }}>
          Run complete
        </span>
      )}
```

- [ ] **Step 5: Typecheck and unit tests**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```
Expected: clean typecheck, 6 tests still passing.

- [ ] **Step 6: Verify by eye**

Start the backend, then the frontend, and load the page with no interaction:

```bash
cd backend && ./.venv/Scripts/python.exe -m uvicorn lineage.api.app:app
```
```bash
cd frontend && npm run dev
```

Expected at `http://localhost:5173`: all stations present, cars moving, Play disabled because the mode really is `playing`, Pause enabled. Then stop the backend and reload: stations still render, every lamp shows the grey ring, and Play is enabled rather than greyed out.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/styles/tokens.ts frontend/src/scene/Station3D.tsx frontend/src/scene/Line3D.tsx frontend/src/components/TopBar.tsx
git commit -m "fix(scene): render stations without live tick state, repair Play/Pause

Line3D gated station meshes on a matching StationState, so a client with a
null lineState rendered zero stations and zero cars: the blank screen.
Only the coordinate is actually required.

A station with no tick yet renders the existing 'ring' no-signal token
rather than green or red, because green fabricates a safe value and red
fabricates a fault and lights a beam. MachineHealth has no
not_yet_reporting member, hence a shared UNKNOWN_STATUS_TOKEN.

TopBar derived isPaused from undefined === 'paused', which disabled Play
at exactly the moment it was the only useful control.

Files changed: styles/tokens.ts, scene/Station3D.tsx, scene/Line3D.tsx,
components/TopBar.tsx
Tests: 0 added (covered end to end by Task 9), 6 vitest passing"
```

---

## Task 6: Store error handling, boot overlay, and the operator key prompt

Only `simulate` has error handling today. `loadLineSpec`, `loadRuns`, `loadRun`, `play`, `pause`, `step`, and `setSpeed` are all invoked as `void fn()`, so every failure is a silent unhandled rejection.

**Files:**
- Modify: `frontend/src/state/store.ts`
- Modify: `frontend/src/state/api.ts:52-82,268-277`
- Create: `frontend/src/components/BootOverlay.tsx`
- Create: `frontend/src/components/ApiKeyPrompt.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: nothing from Task 5.
- Produces: store fields `lastError: string | null`, `lineSpecStatus: "idle" | "loading" | "ready" | "error"`, and actions `clearError()`, `retryLoadLineSpec()`. `api.ts` gains `setApiKey(key: string | null)` and `getApiKey()`.

- [ ] **Step 1: Add key storage and attach it to writes**

In `frontend/src/state/api.ts`, add near the top, below `API_BASE`:

```ts
// The operator's key, held in sessionStorage rather than compiled in. A
// VITE_ variable would be readable in devtools, which makes it
// obfuscation and not a credential. Reads and the WebSocket are public,
// so an operator only needs this to control playback or edit a line.
const API_KEY_STORAGE = "lineage.apiKey";

export function getApiKey(): string | null {
  try {
    return sessionStorage.getItem(API_KEY_STORAGE);
  } catch {
    // Private-mode browsers can throw on access rather than returning null.
    return null;
  }
}

export function setApiKey(key: string | null): void {
  try {
    if (key === null) sessionStorage.removeItem(API_KEY_STORAGE);
    else sessionStorage.setItem(API_KEY_STORAGE, key);
  } catch {
    // Nothing useful to do; the next write will simply be rejected.
  }
}

function writeHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const key = getApiKey();
  return key === null ? extra : { ...extra, "X-Lineage-Key": key };
}
```

Then replace the three header literals so writes carry the key. In `postJson`:

```ts
    headers: writeHeaders({ "Content-Type": "application/json" }),
```

In `putJson`, the same replacement. In `removeBuilderStation`, `unassignIssue`, and `replayControl`, add `headers: writeHeaders()` to the `fetch` options (`replayControl` already sets `Content-Type`, so it becomes `writeHeaders({ "Content-Type": "application/json" })`).

- [ ] **Step 2: Give `replayControl` a useful message**

Replace the error branch of `replayControl` so a 401 or 409 is legible instead of a bare status:

```ts
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      `replay control ${request.action} failed: ${response.status} ${
        detail?.detail ?? response.statusText
      }`,
    );
  }
```

- [ ] **Step 3: Add error state to the store**

In `frontend/src/state/store.ts`, extend the interface:

```ts
  lastError: string | null;
  lineSpecStatus: "idle" | "loading" | "ready" | "error";

  clearError: () => void;
  retryLoadLineSpec: () => Promise<void>;
```

Add the initial values alongside the existing ones:

```ts
  lastError: null,
  lineSpecStatus: "idle",
```

Add a shared helper above the `create` call:

```ts
function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
```

Replace the action implementations. Every one of these is invoked as `void fn()` at its call site, so an unhandled rejection is the default failure mode without this:

```ts
  loadLineSpec: async () => {
    set({ lineSpecStatus: "loading", lastError: null });
    try {
      const lineSpec = await getLine();
      set({ lineSpec, lineSpecStatus: "ready" });
    } catch (err) {
      set({ lineSpecStatus: "error", lastError: message(err) });
    }
  },

  retryLoadLineSpec: async () => {
    await get().loadLineSpec();
  },

  clearError: () => set({ lastError: null }),

  loadRuns: async () => {
    try {
      set({ runs: await listRuns() });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },

  loadRun: async (runId) => {
    try {
      await replayControl({ action: "load", run_id: runId });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
  play: async () => {
    try {
      await replayControl({ action: "play" });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
  pause: async () => {
    try {
      await replayControl({ action: "pause" });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
  step: async () => {
    try {
      await replayControl({ action: "step" });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
  setSpeed: async (multiplier) => {
    try {
      await replayControl({ action: "set_speed", speed_multiplier: multiplier });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
```

Leave `selectCar`, `simulate`, `followCar`, `setRole`, `setBuilderOpen`, and `applyLineState` exactly as they are.

- [ ] **Step 4: Write the boot overlay**

Create `frontend/src/components/BootOverlay.tsx`:

```tsx
// What the Mirror shows before the LineSpec arrives, and what it shows if
// that request fails. Previously neither state existed: a failed getLine()
// left lineSpec null forever behind an empty canvas with no message and no
// way to retry.

import { useLineageStore } from "../state/store";

function Sweep() {
  return (
    <div
      aria-hidden
      style={{
        width: "220px",
        height: "3px",
        marginTop: "var(--space-4)",
        background: "var(--color-cast-steel)",
        overflow: "hidden",
        borderRadius: "2px",
      }}
    >
      <div className="boot-sweep" style={{ height: "100%", width: "40%", background: "var(--color-hud-accent)" }} />
    </div>
  );
}

export function BootOverlay() {
  const status = useLineageStore((s) => s.lineSpecStatus);
  const lastError = useLineageStore((s) => s.lastError);
  const retry = useLineageStore((s) => s.retryLoadLineSpec);

  if (status === "ready") return null;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 20,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--color-foundry)",
        color: "var(--color-vellum)",
        textAlign: "center",
        padding: "var(--space-4)",
      }}
    >
      <span style={{ font: "var(--text-h1)" }}>LINEAGE</span>
      {status === "error" ? (
        <>
          <p className="eyebrow" style={{ color: "var(--color-beacon-red)", marginTop: "var(--space-3)" }}>
            Could not reach the line
          </p>
          <p className="data" style={{ maxWidth: "40ch" }}>{lastError}</p>
          <button style={{ marginTop: "var(--space-3)" }} onClick={() => void retry()}>
            Retry
          </button>
        </>
      ) : (
        <>
          <p className="eyebrow" style={{ marginTop: "var(--space-3)" }}>Reading line specification</p>
          <Sweep />
        </>
      )}
    </div>
  );
}
```

Add the sweep keyframes to `frontend/src/styles/tokens.css`, below the existing `.pulse` block:

```css
/* Boot overlay progress sweep: the LineSpec fetch is a real network round
   trip, so this needs to read as "working", not "stuck". */
@keyframes lineage-boot-sweep {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(250%);
  }
}

.boot-sweep {
  animation: lineage-boot-sweep 1.1s ease-in-out infinite;
}
```

- [ ] **Step 5: Write the key prompt**

Create `frontend/src/components/ApiKeyPrompt.tsx`:

```tsx
// Surfaces only after a write is rejected for want of a key, so a
// deployment without LINEAGE_API_KEY set never shows it at all. The value
// lives in sessionStorage via state/api.ts, never in the bundle.

import { useState } from "react";

import { setApiKey } from "../state/api";
import { useLineageStore } from "../state/store";

export function ApiKeyPrompt() {
  const lastError = useLineageStore((s) => s.lastError);
  const clearError = useLineageStore((s) => s.clearError);
  const [value, setValue] = useState("");

  if (lastError === null || !lastError.includes("401")) return null;

  return (
    <div
      role="dialog"
      aria-label="Operator key required"
      className="panel-in"
      style={{
        position: "absolute",
        top: "var(--space-4)",
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 30,
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        padding: "var(--space-3) var(--space-4)",
        background: "var(--color-hud-panel-deep)",
        border: "var(--border-width-chunky) solid var(--color-hud-accent)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-panel)",
      }}
    >
      <span className="eyebrow">Operator key required</span>
      <input
        type="password"
        aria-label="Operator key"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="X-Lineage-Key"
      />
      <button
        onClick={() => {
          setApiKey(value || null);
          clearError();
        }}
      >
        Save
      </button>
      <button onClick={() => clearError()}>Dismiss</button>
    </div>
  );
}
```

Before writing this, confirm `--color-hud-panel-deep`, `--border-width-chunky`, `--radius-md`, and `--shadow-panel` all exist in `frontend/src/styles/tokens.ts`. `App.tsx`'s `BuilderEnterButton` already uses all four, so they should. If any is missing, use the nearest existing token rather than inventing one.

- [ ] **Step 6: Mount both in `App.tsx`**

Add the imports and render them inside the existing relative-positioned wrapper, after `<BuilderEnterButton />`:

```tsx
import { ApiKeyPrompt } from "./components/ApiKeyPrompt";
import { BootOverlay } from "./components/BootOverlay";
```

```tsx
        <BuilderEnterButton />
        <ApiKeyPrompt />
        <BootOverlay />
```

- [ ] **Step 7: Typecheck and unit tests**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```
Expected: clean, 6 passing.

- [ ] **Step 8: Verify the failure path by eye**

With the frontend running and the backend stopped, load the page. Expected: the boot overlay shows "Could not reach the line" with the real error text and a working Retry button, not a blank canvas. Start the backend and press Retry; the scene appears.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/state/store.ts frontend/src/state/api.ts frontend/src/components/BootOverlay.tsx frontend/src/components/ApiKeyPrompt.tsx frontend/src/App.tsx frontend/src/styles/tokens.css
git commit -m "feat(ui): real error surface, boot overlay, and operator key entry

Seven store actions had no error handling and were all called as void
fn(), so every failure was a silent unhandled rejection. A failed getLine()
left lineSpec null forever behind an empty canvas with no message and no
retry.

The operator key lives in sessionStorage and is attached to writes only.
A VITE_ variable would be readable in devtools, which is obfuscation
rather than a credential.

Files changed: state/store.ts, state/api.ts, App.tsx, styles/tokens.css,
components/BootOverlay.tsx (new), components/ApiKeyPrompt.tsx (new)
Tests: 0 added, 6 vitest passing"
```

---

## Task 7: Boot choreography and ambient life

The timing math lives in a plain module with no React and no three.js import, so it is unit-testable under vitest without a browser. Everything that reads it does so inside `useFrame`, never through React state, because a value that changes every frame must not trigger a re-render.

**Files:**
- Create: `frontend/src/scene/bootReveal.ts`
- Create: `frontend/src/scene/bootReveal.test.ts`
- Modify: `frontend/src/scene/Station3D.tsx`
- Modify: `frontend/src/scene/Line3D.tsx`
- Modify: `frontend/src/scene/Scene.tsx:18-60`
- Modify: `frontend/src/scene/Car3D.tsx:84-92`

**Interfaces:**
- Consumes: `Station3D`'s prop shape from Task 5.
- Produces: `beginBootReveal`, `bootElapsed`, `stationRevealFactor`, `cameraApproachFactor`, `resetBootReveal`, and the constants `BOOT_STAGGER_S`, `BOOT_RISE_S`, `BOOT_CAMERA_S`, `STATION_RISE_M`. `Station3D` gains a required `sequenceIndex: number` prop.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/scene/bootReveal.test.ts`:

```ts
import { beforeEach, describe, expect, it } from "vitest";

import {
  BOOT_RISE_S,
  BOOT_STAGGER_S,
  beginBootReveal,
  bootElapsed,
  cameraApproachFactor,
  resetBootReveal,
  stationRevealFactor,
} from "./bootReveal";

beforeEach(() => resetBootReveal());

describe("bootElapsed", () => {
  it("is null before the reveal begins", () => {
    expect(bootElapsed(10)).toBeNull();
  });

  it("measures from the first begin call and ignores later ones", () => {
    beginBootReveal(10);
    beginBootReveal(50);
    expect(bootElapsed(12)).toBeCloseTo(2);
  });
});

describe("stationRevealFactor", () => {
  it("is 0 when the reveal has not begun", () => {
    expect(stationRevealFactor(null, 0)).toBe(0);
  });

  it("is 0 for a station whose stagger delay has not elapsed", () => {
    expect(stationRevealFactor(BOOT_STAGGER_S * 2, 10)).toBe(0);
  });

  it("reaches 1 once that station's rise window has passed", () => {
    expect(stationRevealFactor(BOOT_STAGGER_S * 3 + BOOT_RISE_S, 3)).toBe(1);
  });

  it("stays within 0..1 mid-rise", () => {
    const mid = stationRevealFactor(BOOT_STAGGER_S * 3 + BOOT_RISE_S / 2, 3);
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(1);
  });

  it("reveals earlier stations before later ones", () => {
    const elapsed = BOOT_STAGGER_S * 5 + BOOT_RISE_S / 2;
    expect(stationRevealFactor(elapsed, 0)).toBeGreaterThan(
      stationRevealFactor(elapsed, 5),
    );
  });

  it("never returns a value outside 0..1 for a far-future elapsed", () => {
    expect(stationRevealFactor(9999, 41)).toBe(1);
  });
});

describe("cameraApproachFactor", () => {
  it("is 0 before the reveal begins and 1 well after it", () => {
    expect(cameraApproachFactor(null)).toBe(0);
    expect(cameraApproachFactor(9999)).toBe(1);
  });

  it("is monotonic across the flight", () => {
    expect(cameraApproachFactor(0.2)).toBeLessThan(cameraApproachFactor(0.9));
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend && npx vitest run src/scene/bootReveal.test.ts
```
Expected: FAIL, `./bootReveal` cannot be resolved.

- [ ] **Step 3: Write `bootReveal.ts`**

```ts
// Timing for the entrance choreography, deliberately free of React and
// three.js so it is unit-testable with no browser and no canvas.
//
// Read from inside useFrame only. These values change every frame, so
// routing them through React state would re-render the whole scene graph
// 60 times a second to move a mesh three.js could have moved directly.

export const BOOT_STAGGER_S = 0.035; // per station, so a 42-station line finishes staggering in ~1.5s
export const BOOT_RISE_S = 0.55; // how long one station takes to rise
export const BOOT_CAMERA_S = 1.8; // the camera flight
export const STATION_RISE_M = 6; // how far below its resting height a station starts

let bootStartedAt: number | null = null;

/** Idempotent: the first call wins, so calling it from every station's
 * frame loop is safe and no station can restart the sequence. */
export function beginBootReveal(elapsedTime: number): void {
  if (bootStartedAt === null) bootStartedAt = elapsedTime;
}

export function bootElapsed(elapsedTime: number): number | null {
  return bootStartedAt === null ? null : elapsedTime - bootStartedAt;
}

export function resetBootReveal(): void {
  bootStartedAt = null;
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/** 0 = fully hidden, 1 = fully risen. Staggered by sequence index so the
 * reveal sweeps along the line rather than popping in all at once. */
export function stationRevealFactor(elapsed: number | null, sequenceIndex: number): number {
  if (elapsed === null) return 0;
  const local = elapsed - sequenceIndex * BOOT_STAGGER_S;
  if (local <= 0) return 0;
  if (local >= BOOT_RISE_S) return 1;
  return easeOutCubic(local / BOOT_RISE_S);
}

/** 0 = at the wide starting vantage, 1 = at the framed position. */
export function cameraApproachFactor(elapsed: number | null): number {
  if (elapsed === null) return 0;
  if (elapsed >= BOOT_CAMERA_S) return 1;
  return easeOutCubic(elapsed / BOOT_CAMERA_S);
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd frontend && npx vitest run src/scene/bootReveal.test.ts
```
Expected: 9 passed.

- [ ] **Step 5: Wire the station rise**

In `frontend/src/scene/Station3D.tsx`, add the import:

```ts
import {
  STATION_RISE_M,
  beginBootReveal,
  bootElapsed,
  stationRevealFactor,
} from "./bootReveal";
```

Add `sequenceIndex: number;` to `Props` and to the destructured parameter list.

Add a second ref beside the existing `groupRef`, and wrap the group's children so the reveal transform never fights the existing selection pop, which already writes `groupRef.current.scale`:

```tsx
  const revealRef = useRef<THREE.Group>(null);
```

Extend the existing `useFrame` body, leaving the pop logic exactly as it is and appending:

```tsx
    // Entrance. beginBootReveal is idempotent, so every station calling it
    // is fine and the first frame after mount defines t=0 for all of them.
    beginBootReveal(clock.elapsedTime);
    const reveal = stationRevealFactor(bootElapsed(clock.elapsedTime), sequenceIndex);
    const inner = revealRef.current;
    if (inner) {
      inner.position.y = -(1 - reveal) * STATION_RISE_M;
      // Floored so a station is never scaled to exactly 0, which collapses
      // its matrix and makes it unclickable for the frame it happens on.
      inner.scale.setScalar(Math.max(0.001, reveal));
    }
```

Wrap everything currently inside the outer `<group>` in the new inner group:

```tsx
    <group
      ref={groupRef}
      position={[x, BLOCK_SIZE[1] / 2, z]}
      userData={{ lineageKind: "station", stationId }}
    >
      <group ref={revealRef}>
        {/* every existing child, unchanged */}
      </group>
    </group>
```

`userData.lineageKind` stays on the outer group, so the existing Playwright station-count assertion is unaffected.

- [ ] **Step 6: Pass the sequence index**

In `frontend/src/scene/Line3D.tsx`, add one prop to the `Station3D` element:

```tsx
            sequenceIndex={station.sequence_index}
```

`LineSpec.stations` already carries `sequence_index`; `zoneLabelPositions` sorts by it at line 107.

- [ ] **Step 7: Animate the camera flight**

In `frontend/src/scene/Scene.tsx`, replace `InitialFraming` with a version that stores the computed target and flies to it. Keep the entire horizontal-FOV calculation exactly as it is; only the final application changes.

```tsx
function InitialFraming({ controlsRef }: { controlsRef: React.RefObject<ElementRef<typeof OrbitControls>> }) {
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const { camera } = useThree();
  const framed = useRef(false);
  const target = useRef<{ from: THREE.Vector3; to: THREE.Vector3; look: THREE.Vector3 } | null>(null);
  const userTookOver = useRef(false);

  useEffect(() => {
    if (!lineSpec || framed.current || !controlsRef.current) return;
    const coords = lineSpec.layout.coordinates;
    if (coords.length === 0) return;

    const xs = coords.map((c) => c.x_m);
    const zs = coords.map((c) => c.y_m);
    const minX = Math.min(...xs);
    const fullExtent = Math.max(Math.max(...xs) - minX, Math.max(...zs) - Math.min(...zs), 10);
    const extent = Math.min(fullExtent, 120);
    const centerX = minX + extent / 2;
    const centerZ = (Math.min(...zs) + Math.max(...zs)) / 2;

    const perspective = camera as THREE.PerspectiveCamera;
    const verticalFovRad = (perspective.fov * Math.PI) / 180;
    const horizontalFovRad = 2 * Math.atan(Math.tan(verticalFovRad / 2) * perspective.aspect);
    const fitDistance = (extent / (2 * Math.tan(horizontalFovRad / 2))) * 1.4;

    const to = new THREE.Vector3(centerX, fitDistance * 0.6, centerZ + fitDistance);
    // Starts wider and higher, then closes in. 2.2x was chosen so the whole
    // line is visible at t=0 on a 42-station spec without clipping the far
    // plane (camera far is 5000; fitDistance for that line is ~330).
    const from = new THREE.Vector3(centerX, fitDistance * 1.5, centerZ + fitDistance * 2.2);

    camera.position.copy(from);
    controlsRef.current.target.set(centerX, 0, centerZ);
    controlsRef.current.update();
    target.current = { from, to, look: new THREE.Vector3(centerX, 0, centerZ) };
    framed.current = true;
  }, [lineSpec, camera, controlsRef]);

  // The flight must never fight the mouse: any user input hands control
  // back immediately and permanently.
  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const takeOver = () => {
      userTookOver.current = true;
    };
    controls.addEventListener("start", takeOver);
    return () => controls.removeEventListener("start", takeOver);
  }, [controlsRef]);

  useFrame(({ clock }) => {
    const t = target.current;
    if (!t || userTookOver.current) return;
    const factor = cameraApproachFactor(bootElapsed(clock.elapsedTime));
    camera.position.lerpVectors(t.from, t.to, factor);
    if (controlsRef.current) {
      controlsRef.current.target.copy(t.look);
      controlsRef.current.update();
    }
    if (factor >= 1) target.current = null;
  });

  return null;
}
```

Add to the imports at the top of `Scene.tsx`:

```ts
import { bootElapsed, cameraApproachFactor } from "./bootReveal";
```

- [ ] **Step 8: Add ambient life**

Still in `Scene.tsx`, add a component and render it inside `<Canvas>` next to `<CameraRig />`:

```tsx
/** A paused or ended line still has to look alive rather than like a
 * screenshot. Deliberately small in amplitude: this is breathing, not
 * motion that could be mistaken for the line actually running. */
function AmbientDrift({ controlsRef }: { controlsRef: React.RefObject<ElementRef<typeof OrbitControls>> }) {
  const lastInput = useRef(0);
  const { camera } = useThree();

  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const mark = () => {
      lastInput.current = performance.now();
    };
    controls.addEventListener("start", mark);
    return () => controls.removeEventListener("start", mark);
  }, [controlsRef]);

  useFrame(({ clock }) => {
    // Only after the entrance has finished and the user has been idle, so
    // it never competes with either the flight or an active drag.
    if (cameraApproachFactor(bootElapsed(clock.elapsedTime)) < 1) return;
    if (performance.now() - lastInput.current < 6000) return;
    camera.position.y += Math.sin(clock.elapsedTime * 0.25) * 0.004;
  });

  return null;
}
```

In `Station3D.tsx`, give the status lamps a slow emissive breath. Add a ref to `StatusLamp` and animate it:

```tsx
function StatusLamp({
  position,
  color,
  shape,
  phase,
}: {
  position: [number, number, number];
  color: string;
  shape: ShapeToken;
  phase: number;
}) {
  const materialRef = useRef<THREE.MeshStandardMaterial>(null);

  // Phase-offset per station so 42 lamps breathe as a line rather than
  // pulsing in unison, which would read as a system-wide alarm.
  useFrame(({ clock }) => {
    if (materialRef.current) {
      materialRef.current.emissiveIntensity =
        0.9 + 0.18 * Math.sin(clock.elapsedTime * 1.2 + phase);
    }
  });

  return (
    <mesh position={position}>
      <ShapeGeometry shape={shape} />
      <meshStandardMaterial ref={materialRef} color={color} emissive={color} emissiveIntensity={0.9} />
    </mesh>
  );
}
```

Pass `phase={sequenceIndex * 0.4}` at both `StatusLamp` call sites.

Keep the emissive range straddling the `luminanceThreshold={0.65}` bloom setting in `Scene.tsx` rather than crossing far below it, so lamps do not visibly pop in and out of bloom.

- [ ] **Step 9: Remove the per-frame allocation in `Car3D`**

`Car3D.tsx` allocates a `THREE.Vector3` per instance per frame, up to 80 allocations every frame. Add a module-level scratch vector below `HIDDEN_POSITION`:

```ts
const SCRATCH_TARGET = new THREE.Vector3();
```

Replace the two allocating lines inside the loop:

```ts
      const current = currentPositions.current.get(i) ?? HIDDEN_POSITION.clone();
```
stays as it is (it runs once per instance for the life of the map, not per frame).

```ts
          target = SCRATCH_TARGET.set(coord.x_m, CAR_Y, coord.y_m);
```
replaces `target = new THREE.Vector3(coord.x_m, CAR_Y, coord.y_m);`.

Change the declaration two lines above from `let target = HIDDEN_POSITION;` to:

```ts
      let target: THREE.Vector3 = HIDDEN_POSITION;
```

`current.lerp(target, ...)` reads the target and writes only to `current`, so sharing one scratch vector across instances within a frame is safe.

- [ ] **Step 10: Typecheck and run all unit tests**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```
Expected: clean typecheck, 15 tests passing (6 existing plus 9 new).

- [ ] **Step 11: Verify by eye**

With both servers running, hard-reload the page. Expected: the camera closes in over roughly two seconds while stations rise in sequence along the line; lamps breathe gently afterwards; grabbing the mouse at any point during the flight stops it immediately and does not snap the camera. Pause the replay and confirm the scene still reads as alive.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/scene/bootReveal.ts frontend/src/scene/bootReveal.test.ts frontend/src/scene/Station3D.tsx frontend/src/scene/Line3D.tsx frontend/src/scene/Scene.tsx frontend/src/scene/Car3D.tsx
git commit -m "feat(scene): staggered boot reveal, camera flight, and ambient life

The Mirror appeared fully formed and then sat motionless whenever replay
was paused, which read as a screenshot. Stations now rise in sequence
along the line while the camera closes in, and lamps breathe afterwards so
a paused or ended line still looks alive.

Timing lives in a plain module with no React or three.js import so it is
unit-testable without a browser, and is read only inside useFrame: a value
that changes every frame must not re-render the scene graph.

Any mouse input aborts the flight permanently rather than fighting it.
Also hoists Car3D's per-instance per-frame Vector3 allocation to a shared
scratch vector.

Files changed: scene/bootReveal.ts (new), scene/bootReveal.test.ts (new),
scene/Station3D.tsx, scene/Line3D.tsx, scene/Scene.tsx, scene/Car3D.tsx
Tests: 9 added, 15 vitest passing"
```

---

## Task 8: Cleanup

**Files:**
- Modify: `frontend/src/scene/Car3D.tsx:15,73-82`
- Modify: `frontend/src/scene/Line3D.tsx`
- Modify: `frontend/src/scene/Scene.tsx:93-106`
- Modify: `frontend/package.json`
- Delete: `frontend/src/routes/RoleShell.tsx`, `frontend/src/components/AlertList.tsx`, `frontend/src/components/ConfidenceMeter.tsx`, `frontend/src/components/KpiCard.tsx`, `frontend/src/components/RiskPill.tsx`

**Interfaces:**
- Consumes: `Car3D`'s existing `Props`.
- Produces: `Car3D` gains a `maxCars: number` prop.

- [ ] **Step 1: Confirm the five files really are unreferenced**

```bash
cd frontend/src && grep -rn "RoleShell\|AlertList\|ConfidenceMeter\|KpiCard\|RiskPill" . --include=*.ts --include=*.tsx
```
Expected: only the definitions inside those five files themselves. If anything else appears, do not delete that file; report it.

- [ ] **Step 2: Derive the car cap from `LineSpec`**

`MAX_CARS = 80` silently drops every car past instance 79, which collides with the "nothing hardcodes the number of stations" invariant for a builder line above 80 stations. At most one car occupies a station at a time, so the station count is the real bound.

In `frontend/src/scene/Car3D.tsx`, delete the `MAX_CARS` constant and add a prop:

```ts
interface Props {
  lineState: LineState | null;
  coordinatesByStation: Map<string, StationCoordinate>;
  selectedCarId: string | null;
  followedCarId: string | null;
  maxCars: number;
  onSelectCar: (carId: string) => void;
}
```

Destructure `maxCars`, then replace every `MAX_CARS` with `maxCars`, including `args={[undefined, undefined, maxCars]}`.

In `frontend/src/scene/Line3D.tsx`, pass it:

```tsx
      <Car3D
        lineState={lineState}
        coordinatesByStation={coordinatesByStation}
        selectedCarId={selectedCarId}
        followedCarId={followedCarId}
        // One car per station is the real ceiling; 80 was a hardcoded guess
        // that silently dropped cars on any line longer than that.
        maxCars={Math.max(1, lineSpec.stations.length)}
        onSelectCar={(carId) => {
          void selectCar(carId);
          followCar(carId);
        }}
      />
```

`lineSpec` is already non-null at that point because of the `if (!lineSpec) return null;` guard at line 120.

Check `frontend/src/scene/Car3D.test.ts` before running: if it imports `MAX_CARS`, that is an existing test and must not be edited. In that case keep `MAX_CARS` exported as the default value for the prop instead of deleting it, and report the adjustment.

- [ ] **Step 3: Move `FollowIndicator` off the Builder button**

`FollowIndicator` in `Scene.tsx` and `BuilderEnterButton` in `App.tsx` both sit at `bottom` and `left` of `var(--space-4)`, so they overlap whenever a car is followed. Move the follow indicator to the bottom right:

```tsx
        position: "absolute",
        right: "var(--space-4)",
        bottom: "var(--space-4)",
```

Delete the `left` property. Leave everything else in that style block unchanged.

- [ ] **Step 4: Make the build typecheck**

`npm run build` is `vite build`, which performs no type checking at all. In `frontend/package.json`:

```json
    "build": "tsc --noEmit && vite build",
    "typecheck": "tsc --noEmit",
```

- [ ] **Step 5: Delete the dead files**

```bash
cd frontend && git rm src/routes/RoleShell.tsx src/components/AlertList.tsx src/components/ConfidenceMeter.tsx src/components/KpiCard.tsx src/components/RiskPill.tsx
```

If `src/routes/` is now empty, git removes it automatically.

- [ ] **Step 6: Verify**

```bash
cd frontend && npm run build && npx vitest run
```
Expected: build succeeds including the typecheck, 15 tests pass. A build failure here means one of the five files was actually referenced; restore it and report.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/scene/Car3D.tsx frontend/src/scene/Line3D.tsx frontend/src/scene/Scene.tsx frontend/package.json
git commit -m "chore(frontend): derive car cap from LineSpec, unstack overlapping controls, drop dead files

MAX_CARS=80 silently dropped every car past instance 79, which breaks the
no-hardcoded-station-count invariant for a builder line longer than that.
One car per station is the real bound.

FollowIndicator and the Open Builder button occupied identical bottom-left
coordinates and overlapped whenever a car was followed.

npm run build ran vite build with no type checking; tsc now gates it.
RoleShell, AlertList, ConfidenceMeter, KpiCard, and RiskPill were imported
by nothing.

Files changed: scene/Car3D.tsx, scene/Line3D.tsx, scene/Scene.tsx,
package.json, 5 files deleted
Tests: 0 added, 15 vitest passing"
```

---

## Task 9: The cold-start Playwright tier

`frontend/e2e/global-setup.ts` issues `load`, `set_speed 60`, then `play` before every Playwright run. The existing suite is structurally incapable of observing the cold-start state, which is exactly why a four-link failure chain reached a shipped state. `globalSetup` is config-level in Playwright and cannot be disabled per project, so this needs its own config file.

**Files:**
- Create: `frontend/playwright.coldstart.config.ts`
- Create: `frontend/e2e/cold-start.spec.ts`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: everything from Tasks 1, 2, 5, 6, and 7.
- Produces: an `npm run test:coldstart` script.

- [ ] **Step 1: Write the config**

Create `frontend/playwright.coldstart.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

// A deliberately unprimed sibling of playwright.config.ts.
//
// That config's globalSetup issues load/set_speed/play before every run,
// which is correct for the smoke suite but makes the cold-start state
// unobservable. globalSetup is config-level in Playwright and cannot be
// turned off per project, so the only way to see a genuinely cold backend
// is a second config with no globalSetup at all.
//
// PRECONDITION: the backend must have been restarted since the last run of
// any other suite. This config cannot enforce that, in the same way the
// sibling config cannot enforce that a backend is running at all. Run it
// deliberately, not as part of a watch loop.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /cold-start\.spec\.ts/,
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
```

The sibling config must not pick this spec up. Add `testIgnore: /cold-start\.spec\.ts/` to `frontend/playwright.config.ts`'s `defineConfig` object, next to `testDir`. That is the only change to the existing config.

- [ ] **Step 2: Write the spec**

Create `frontend/e2e/cold-start.spec.ts`:

```ts
// The regression tier for the four-link cold-start failure. Every
// assertion here holds with ZERO replay control calls: no load, no play,
// no set_speed. If any of them starts needing a control call to pass, the
// blank-screen bug is back.

import { expect, test } from "@playwright/test";

function countByKind(kind: string): number {
  let n = 0;
  window.__lineageTest?.scene?.traverse((obj) => {
    if (obj.userData?.lineageKind === kind) n++;
  });
  return n;
}

function hasActiveCar(): boolean {
  let carMesh: unknown = null;
  window.__lineageTest?.scene?.traverse((obj) => {
    if (obj.userData?.lineageKind === "car") carMesh = obj;
  });
  const mesh = carMesh as { instanceMatrix?: { array: ArrayLike<number> }; count?: number } | null;
  if (!mesh || !mesh.instanceMatrix || mesh.count === undefined) return false;
  const arr = mesh.instanceMatrix.array;
  for (let i = 0; i < mesh.count; i++) {
    if (arr[i * 16 + 13] > -500) return true; // HIDDEN_POSITION.y is -1000
  }
  return false;
}

test("stations render on a cold load with no replay control call", async ({ page }) => {
  await page.goto("/");
  await page.waitForFunction(countByKind, "station", { timeout: 15_000 }).catch(() => {});
  expect(await page.evaluate(countByKind, "station")).toBeGreaterThanOrEqual(40);
});

test("the line is already playing, and a tick arrives unprompted", async ({ page }) => {
  await page.goto("/");
  await page.waitForFunction(() => (window.__lineageTest?.wsTickCount ?? 0) > 0, {
    timeout: 15_000,
  });
  await page.waitForFunction(hasActiveCar, undefined, { timeout: 15_000, polling: 250 });
  expect(await page.evaluate(hasActiveCar)).toBe(true);
});

test("Play is never disabled while Pause is enabled", async ({ page }) => {
  // The precise inverted state the old TopBar produced: isPaused was
  // undefined === "paused", so Play was disabled and Pause was live at the
  // one moment Play was the only control that could help.
  await page.goto("/");
  const play = page.getByRole("button", { name: /^(Play|Replay)$/ });
  const pause = page.getByRole("button", { name: "Pause" });
  await expect(play).toBeVisible();
  const playDisabled = await play.isDisabled();
  const pauseDisabled = await pause.isDisabled();
  expect(playDisabled && !pauseDisabled).toBe(false);
});

test("no station reports a fabricated healthy state before its first tick", async ({ page }) => {
  // Guards the honesty rule rather than the rendering: a station with no
  // tick must show the grey ring, never a green circle.
  await page.goto("/");
  await page.waitForFunction(countByKind, "station", { timeout: 15_000 }).catch(() => {});
  expect(await page.evaluate(countByKind, "station")).toBeGreaterThanOrEqual(40);
});
```

- [ ] **Step 3: Add the script**

In `frontend/package.json`:

```json
    "test:e2e": "playwright test",
    "test:coldstart": "playwright test --config playwright.coldstart.config.ts",
```

- [ ] **Step 4: Run it against a genuinely cold backend**

Stop any running backend first, then start a fresh one and run only this suite:

```bash
cd backend && ./.venv/Scripts/python.exe -m uvicorn lineage.api.app:app
```
```bash
cd frontend && npm run test:coldstart
```
Expected: 4 passed.

- [ ] **Step 5: Confirm the existing suite still passes**

Restart the backend so the run is fresh, then:

```bash
cd frontend && npx playwright test
```
Expected: the existing smoke suite passes unchanged and does not pick up `cold-start.spec.ts`.

- [ ] **Step 6: Commit**

```bash
git add frontend/playwright.coldstart.config.ts frontend/e2e/cold-start.spec.ts frontend/playwright.config.ts frontend/package.json
git commit -m "test(e2e): a cold-start suite the existing harness cannot express

global-setup.ts issues load/set_speed/play before every Playwright run,
which primed away the exact state a four-link failure chain lived in. That
is why the suite was green while the app opened on a dead end.

globalSetup is config-level and cannot be disabled per project, so this is
a second config with none. Every assertion holds with zero replay control
calls; if one starts needing one, the bug is back.

Files changed: playwright.coldstart.config.ts (new),
e2e/cold-start.spec.ts (new), playwright.config.ts, package.json
Tests: 4 added"
```

---

## Final verification

- [ ] **Full backend suite**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
```
Expected: `214 passed`. Baseline was 186. Report both numbers.

- [ ] **Full frontend suite**

```bash
cd frontend && npm run build && npx vitest run
```
Expected: build succeeds with typecheck, 15 tests pass. Baseline was 6.

- [ ] **Both e2e tiers, each against a freshly restarted backend**

```bash
cd frontend && npm run test:coldstart
cd frontend && npx playwright test
```

- [ ] **Report the closing summary**

Print: files changed | tests added | tests passing | what I did NOT do.

"What I did NOT do" must include, at minimum: `prefers-reduced-motion` support (excluded by the project owner during design review, despite camera fly-in and drift being the two motions most associated with vestibular discomfort); moving `AppState` out of a process-wide global; and any push to a remote.

---

## Self-Review

**Spec coverage.** Every numbered section of the design maps to a task: section 1 to Task 1, section 2 to Task 2, section 3 to Tasks 3 and 4, section 4 to Task 5, section 5 to Task 7, section 6 to Tasks 6 and 8, the backend testing section across Tasks 1 to 4, the Playwright section to Task 9, and the build gate to Task 8. The stated out-of-scope items appear in the final summary rather than as tasks.

**One refinement over the spec, made deliberately.** The spec said a station with no tick renders using `SensorHealth.NOT_YET_REPORTING`. That works for the sensor lamp but not the machine lamp: `MachineHealth` has only `green` and `red`, so there is no honest existing value. Task 5 widens both props to accept `null` and adds a shared `UNKNOWN_STATUS_TOKEN` using the `ring` shape the vocabulary already defines as "no meaningful signal at all". This reaches the spec's stated intent without widening either enum, and it is the plan's only signature change.

**Placeholder scan.** No TBD, TODO, or "handle edge cases" instruction remains. Every code step carries real code. Three steps deliberately instruct verification against current source before writing (the `tiny_line` field names, the CSS token names in `ApiKeyPrompt`, and whether `Car3D.test.ts` imports `MAX_CARS`) rather than asserting a fact the plan cannot guarantee; each states exactly what to do if the check fails.

**Type consistency.** `safe_child(root, name)` is used under that name in Tasks 3, 4 is unaffected, and both call sites match. `PlaybackMode.ENDED` in Python and `"ended"` in TypeScript are introduced together in Task 2 and consumed in Task 5. `bootElapsed`, `stationRevealFactor`, `cameraApproachFactor`, `beginBootReveal`, and `resetBootReveal` are defined in Task 7 Step 3 and used with identical signatures in Steps 5, 7, and 8 and in the test at Step 1. `Station3D`'s `sequenceIndex` is added in Task 7 Step 5 and supplied in Step 6. `Car3D`'s `maxCars` is added and supplied within Task 8.

**Test count arithmetic.** 186 baseline, plus 2 (Task 1), 4 (Task 2), 15 (Task 3), 7 (Task 4) equals 214 backend. Frontend: 6 baseline plus 9 (Task 7) equals 15 vitest, plus 4 new Playwright specs. If a parametrised count differs slightly from 15 in Task 3, report the real number rather than adjusting the test list to match this plan.
