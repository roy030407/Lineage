# Cold Start, Animation, and Hardening

Date: 2026-08-29
Status: approved, pending implementation plan

## Problem

Opening Lineage against a freshly booted backend produces a dead end. The
screen is effectively blank (a dark background, a few thin conveyor bars, three
zone labels), nothing moves, and the one control that could recover the
situation is disabled.

This is not one defect. It is four independent defects in a chain, each of
which is sufficient on its own to produce the symptom.

### Link 1: the backend never loads a run at boot

`backend/lineage/api/app.py`, `_lifespan` calls `_ensure_default_run_exists()`,
which only writes run files to disk. Nothing ever calls `load_run_into_state`.
So `state.engine` stays `None`, and the background tick loop hits its
`continue` on every iteration forever.

### Link 2: the WebSocket replays an empty history

`backend/lineage/api/routes/mirror.py`, `ws_line` sends
`snapshot_history.recent()` on connect. At boot that deque is empty, so a
connecting client receives zero bytes. The socket is open and healthy, which is
precisely why this does not present as a failure. `lineState` stays `null` in
the client indefinitely.

### Link 3: station meshes are gated on live state

`frontend/src/scene/Line3D.tsx` line 144 reads `if (!coord || !state) return
null;`. Station meshes require a matching `StationState`. With `lineState ===
null`, `stationStateById` is empty, so zero stations and zero cars render. This
is literally the blank screen.

### Link 4: Play is disabled exactly when it is needed

`frontend/src/components/TopBar.tsx` line 38 computes
`isPaused = lineState?.playback_mode === "paused"`. With no state that
evaluates `undefined === "paused"`, which is `false`, so
`<button disabled={!isPaused}>Play</button>` renders disabled while Pause
renders enabled and returns 409. The default state of the application is
unrecoverable through the UI.

### Why the test suite never caught it

`frontend/e2e/global-setup.ts` issues `load`, then `set_speed 60`, then `play`
before every Playwright run. The suite is structurally incapable of observing
the cold-start state. No test anywhere exercises a fresh backend with a fresh
browser.

Separately, `npm run build` is `vite build`, which does not typecheck. `tsc` is
clean today but nothing enforces it.

## Secondary problem discovered during analysis

Auto playing at boot does not remove the blank screen, it delays it.

Measured against the real `default_400_car_run`: the run holds 9h 38m of
simulated time, which is 9.6 minutes of wall clock at the 60x the e2e harness
sets. Past the end of the data, `RunData.car_at_station_at` returns `None` for
every station and `RunData.sensor_is_reporting` returns `RED` for every
station, while `SimClock.auto_tick` keeps advancing with no end bound.

The result is an empty line plus a fabricated all stations RED alarm. That is
the same class of untruth the project invariant "a station with no sensor
returns risk = UNKNOWN, never risk = 0 or safe" exists to prevent, so it must
be fixed as part of this work rather than deferred.

## Security findings

1. **Windows directory escape in `/api/builder/save`.** The handler rejects
   `/`, `\`, `..`, and requires a `.yaml` suffix. The filename `C:evil.yaml`
   passes all four checks. Verified on the development machine:
   `Path("data/lines") / "C:evil.yaml"` resolves to `C:evil.yaml`.
   Drive-relative paths re-anchor and escape `lines_root` entirely.
2. **`run_id` is unvalidated** before `state.runs_root / run_id` in
   `load_run_into_state`. With `..` segments this is an unauthenticated
   existence oracle for arbitrary filesystem paths.
3. **No authentication and no rate limiting**, while `/api/datagen/simulate` is
   an approximately 11s CPU job and `/api/predict/metrics` is a documented
   approximately 105s job, both reachable on a deployment that is deliberately
   pinned to a single worker.

## Smaller defects in scope

- `MAX_CARS = 80` in `frontend/src/scene/Car3D.tsx` silently drops cars past
  index 79, which collides with the "nothing hardcodes the number of stations"
  invariant for any builder line above 80 stations.
- `FollowIndicator` in `Scene.tsx` and `BuilderEnterButton` in `App.tsx` occupy
  identical `bottom`/`left: var(--space-4)` coordinates and overlap whenever a
  car is followed.
- `loadLineSpec`, `loadRuns`, `loadRun`, `play`, `pause`, `step`, and
  `setSpeed` in `state/store.ts` have no error handling (only `simulate` does)
  and are all invoked as `void fn()`, so every failure is a silent unhandled
  rejection.
- Five files are imported by nothing: `routes/RoleShell.tsx`,
  `components/AlertList.tsx`, `ConfidenceMeter.tsx`, `KpiCard.tsx`,
  `RiskPill.tsx`.

## Baselines recorded before any change

| Suite | Result |
| --- | --- |
| `pytest -q` (backend) | 186 passed, 1 warning, 319s |
| `npx tsc --noEmit` (frontend) | clean |
| `npx vitest run` | 6 passed, 2 files |
| Playwright e2e | not run (requires a live backend) |

## Governing constraint

Every existing test is the spec and stays untouched. Two mechanisms make that
possible, and both are load bearing.

**Boot auto-load is guarded on `state.runs_root`, never the module level
`RUNS_ROOT`.** Three tests assert the cold-start 409 behaviour:
`test_replay_control_without_load_returns_conflict`,
`test_get_car_without_load_returns_conflict`, and
`test_role_views_without_load_return_conflict`. All three run the real lifespan
via `with TestClient(create_app())`, and all three use
`runs_root = tmp_path / "runs"` containing only `api-test-run`. A guard that
checks `state.runs_root` returns early in those fixtures, the engine stays
`None`, and the 409 contract is preserved. A guard reading the module level
`RUNS_ROOT` would break all three, because the repository copy of
`default_400_car_run` does exist.

**The auth gate is inert when `LINEAGE_API_KEY` is unset.** The dependency is a
no-op without the environment variable, so all 186 existing tests and local
development continue to work with zero edits. The gate engages only where the
variable is set, which is deployment.

## Design

### 1. Backend: the line is alive at boot

`_lifespan` gains `_autoload_default_run()`, called after the existing
`_ensure_default_run_exists()`. It reads `state.runs_root`, returns early if
`DEFAULT_RUN_ID` is not present there, and otherwise calls the existing
`load_run_into_state`. No new load logic is introduced.

`SimClock` already initialises `mode` to `PLAYING`, so auto play requires no
further change.

`ws_line` gains a fallback: when `snapshot_history` is empty but an engine
exists, send `engine.current_state()` immediately on connect. This removes the
up to one second gap before the first frame, and removes the indefinite wait
when history is empty.

### 2. Backend: end of run is honest

- `PlaybackMode` gains an `ENDED` member. This is additive; the only test that
  references the enum asserts `PAUSED` after a pause call and is unaffected.
- `RunData` gains an `end_time` attribute alongside the existing `start_time`,
  computed from the maximum timestamp across telemetry and events.
- `ReplayEngine.tick()` clamps the clock at `end_time` and sets mode `ENDED`
  instead of advancing into absent data. Because `SimClock.auto_tick` already
  returns early for any mode that is not `PLAYING`, `ENDED` stops the clock
  naturally.
- Pressing Play on an ended run seeks back to `start_time` and resumes, so the
  control is never a no-op.

The frontend `PlaybackMode` union in `state/types.ts` gains `"ended"` to match.

### 3. Backend: security

- A shared `_safe_child(root, name)` helper rejects any name where
  `Path(name).name != name`, rejects `""`, `"."`, and `".."`, then resolves the
  candidate and asserts its parent really is the resolved root. Applied to both
  the builder save filename and to `run_id`. This is what closes
  `C:evil.yaml`, which passes every one of the current checks.
- An `X-Lineage-Key` header dependency guards mutating and expensive routes
  only. GET endpoints and the WebSocket stay public, so the mirror and the role
  views remain usable without a key. The frontend prompts the operator for the
  key and holds it in `sessionStorage`.

  This shape is deliberate. A shared secret compiled into a Vite bundle is
  readable by anyone who opens developer tools, so `VITE_` prefixed
  configuration is not a viable place for a credential. An operator-supplied
  key is a real credential; a bundled one is obfuscation.
- A single-flight lock on `/api/datagen/simulate`, which has none today
  (`predict` already has `prediction_ledger_lock`), plus a small token bucket
  on both expensive endpoints, so one client cannot wedge the single worker.

### 4. Frontend: stations render without live state

`Line3D.tsx` stops gating station meshes on `StationState`. A station with no
state yet renders using the existing `SensorHealth.NOT_YET_REPORTING`
vocabulary, which is already a first-class concept with an established visual
treatment. It is explicitly not rendered green or healthy, which satisfies the
never-fabricate-a-safe-value invariant, and it requires no new enum on either
side.

`TopBar.tsx` derives Play and Pause from real state with an explicit no state
yet branch, so Play is enabled whenever pressing it is meaningful, including at
cold start and after `ENDED`.

### 5. Frontend: boot choreography and ambient life

Entrance, approximately 1.8s, once per load:

- The camera flies in from a wider and higher start to the framed position that
  `InitialFraming` computes today, rather than snapping to it.
- Stations rise and scale in, staggered by `sequence_index`, so the reveal
  sweeps along the line rather than appearing all at once.
- Beacons ignite on the same stagger.
- `OrbitControls` is disabled for the duration of the flight, and the flight
  aborts immediately on any user input. It must never fight the mouse.

Ambient, persistent:

- Beacon emissive breathing.
- Conveyor surface scroll.
- A few degrees of camera drift, engaging only after a period of user
  inactivity.

The ambient layer is what stops a paused or ended line from reading as a
screenshot, which is the actual requirement behind "should not be static".

Before `lineSpec` arrives, a branded boot overlay renders instead of an empty
canvas.

Performance: `Car3D.tsx` line 92 allocates a `THREE.Vector3` per instance per
frame, which is up to 80 allocations per frame of garbage collector pressure.
Since this file is already being edited for `MAX_CARS`, the allocation is
hoisted to a reused scratch vector.

### 6. Frontend: the smaller defects

- Store actions gain error handling with a visible error surface and a retry
  path.
- `FollowIndicator` moves off `BuilderEnterButton`'s coordinates.
- `MAX_CARS` is derived from `LineSpec` rather than hardcoded.
- The five unimported files are deleted.

## Testing

### Backend, new pytest coverage

- Boot auto-load produces an engine and delivers a WebSocket frame with zero
  control calls.
- The `state.runs_root` guard still yields 409 when the default run is absent.
  This test exists specifically to pin the contract the three existing cold
  start tests depend on, so a future change cannot quietly widen the auto-load.
- End of run clamps the clock and reports `ENDED`.
- `C:evil.yaml`, `CON.yaml`, absolute paths, `""`, and `.yaml` all return 400
  from the builder save endpoint.
- `run_id` containing traversal segments returns 400.
- With `LINEAGE_API_KEY` set, a guarded route returns 401 without the header
  and succeeds with it. With the variable unset, the route is open.
- Concurrent calls to `/api/datagen/simulate` do not start two generations.

### Playwright, new cold-start config

A separate `playwright.coldstart.config.ts` with no `globalSetup`, because
`globalSetup` is config-level in Playwright and cannot be disabled per project.
Precondition, documented in the config the same way the existing config
documents its own: a freshly restarted backend.

Assertions: within a bounded wait after `page.goto("/")` and with zero replay
control calls, at least 40 station meshes and at least one car exist in the
scene, and the Play and Pause buttons reflect real playback state.

This tier is not optional. The existing harness primes the backend before every
run, which is the exact blind spot that allowed a four-link failure to reach a
shipped state.

### Build gate

Add a `typecheck` script running `tsc --noEmit` and wire it into `build`, which
performs no type checking today.

## Commit structure

One concern per commit, per the project working rules.

1. backend: boot auto-load and immediate first WebSocket frame
2. backend: `ENDED` playback mode and clock clamp, plus the matching
   `PlaybackMode` union member in `state/types.ts` (one concern, two sides of
   the same contract)
3. backend: path validation for filename and `run_id`
4. backend: auth dependency and denial-of-service guards
5. frontend: render stations without live state, and the Play/Pause state
   machine
6. frontend: store error handling and boot overlay
7. frontend: boot choreography and ambient animation
8. cleanup: `MAX_CARS`, dead files, `FollowIndicator`, typecheck script

## Explicitly out of scope

`prefers-reduced-motion` support was considered and excluded by the project
owner during design review.

This is recorded rather than silently dropped, because camera fly-in and camera
drift are the two motions most associated with vestibular discomfort, so
section 5 introduces an accessibility gap that does not exist today. The
remedy, if it is ever wanted, is a reduced-motion block in `styles/tokens.css`
plus one guard in the camera hook, and it belongs in commit 7.

Also out of scope: moving `AppState` out of a process-wide global. The single
worker constraint documented in `render.yaml` and `api/deps.py` stands
unchanged, and nothing in this design increases the coupling to it.
