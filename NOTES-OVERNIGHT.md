# UI overhaul — progress notes

Branch: `feat/ui-overhaul`. Not run as the unattended overnight process —
done interactively, one task at a time, same rhythm as the rest of this
project, per Prompt A's diagnosis+plan being reviewed live rather than
`--dangerously-skip-permissions` in a separate process.

## Task 1 — Playwright harness ✅

Added `@playwright/test` as a real frontend devDependency (previously
Playwright was scratchpad-only, ad-hoc verification tooling for manual
browser checks). `frontend/playwright.config.ts` + `frontend/e2e/`:

- `global-setup.ts`: fails fast with a clear message if the backend isn't
  reachable (same pattern as `scripts/demo.py`'s `check_prerequisites`),
  then loads and plays `default_400_car_run` so every test starts from the
  same known, already-advancing state.
- `smoke.spec.ts`: 8 tests, all asserting something real and observable:
  - WS connects, ≥1 tick received
  - ≥40 station meshes in the scene (tagged via `userData.lineageKind`)
  - ≥1 car mesh exists with y strictly above the station-block top
    (reads `instanceMatrix.array` directly rather than needing THREE
    exposed on `window` -- element 13 of each instance's 16-float
    column-major matrix is its world Y)
  - all four role views (Operator/Floor Supervisor/Plant Manager/
    Leadership) render distinctive content, not a shared fallback --
    specifically checks Leadership has **zero** `<table>` elements, since
    that's the whole point of its scoping
  - Builder canvas has a spawn tray

**7/8 pass.** The 8th (spawn tray) fails on purpose right now -- today's
Builder is the form-based UI from an earlier task, not the node-graph
canvas Task 8 will build. Left failing and documented rather than
weakened, so it becomes a real gate once Task 8 lands.

Real bug caught building this, not in the app: the first version of the
station/car-mesh tests waited for `scene != null`, which resolves as soon
as the Canvas mounts -- well before `lineSpec`/`lineState` load
asynchronously and `Station3D`/`Car3D` actually populate the scene graph.
Both tests initially failed with count=0 against a scene that was, in
reality, fully rendered. Fixed by polling the real rendered count directly
(`waitForFunction`) instead of a proxy signal for "probably ready by now."

Also added `test.exclude: ["e2e/**"]` to `vite.config.ts` -- vitest's
default glob was picking up `smoke.spec.ts` and failing to parse
Playwright's `test`/`expect` API as its own.

Exposed via `frontend/src/testHooks.ts` (`window.__lineageTest`): a scene
reference (set in `Scene.tsx`'s `Canvas onCreated`) and a WS tick counter
(incremented in `wsClient.ts`). Read-only from the test side, never
mutates app state. `userData.lineageKind` tags added to `Station3D.tsx`'s
group and `Car3D.tsx`'s instancedMesh so tests can identify them reliably
without guessing by geometry type.

Verified: `pytest -q` 137/137, `ruff check .` clean, `tsc --noEmit` clean,
`vitest run` 1/1, production build succeeds, `npx playwright test` 7/8
(1 expected failure, documented above).

## Task 2 — replay/Play bug ✅ (leading cause addressed; one finding held for approval)

Fixed the leading suspected root cause directly: `render.yaml`'s
`startCommand` now pins `--workers 1` explicitly (uvicorn's default in most
contexts, but not guaranteed, and worth being loud about rather than
implicit), and `api/deps.py`'s `_state` global now carries an explicit
docstring explaining exactly why this app cannot run as more than one
process/worker without moving state out of an in-process global first.

Added `test_ticking_advances_time_and_buffer_depths_become_nonzero` to
`tests/unit/test_replay.py` -- empirically confirmed (not assumed) that a
20-car run over 120 ticks both advances simulated time and produces a real
nonzero upstream buffer depth (max observed: 2). This guards the tick
mechanism itself; it does not and cannot reproduce the multi-worker/
multi-instance topology issue in a single-process test.

**Held for explicit approval, not fixed:** the RED-conflation finding
(`sensor_is_reporting` returning `False`/RED both for "gone stale" and
"hasn't reported yet") would need a new `SensorHealth` state to fix
properly, and `tests/unit/test_replay.py::test_station_without_sensors_reports_not_applicable_never_red`
currently asserts `sensor_health in (GREEN, RED)` for an instrumented
station at the very start of a run -- exactly the "hasn't reported yet"
case. Splitting RED into two states would break that existing assertion.
Per this project's own rule ("tests are the spec, stop and ask"), this is
flagged rather than changed.

## Remaining tasks

3. Serpentine layout regeneration
4. Shared design token system
5. 3D Mirror rebuild
6. Role views: Operator, Floor Supervisor, Plant Manager
7. Leadership ROI backend + view
8. Node-graph Builder canvas
9. Final sweep

## Diagnosis on record (Task 2, not yet fixed)

Root cause, ranked by confidence:

1. **(Leading)** `AppState` is a bare process-wide global
   (`api/deps.py`'s `_state`), and the tick loop (`app.py`'s `_tick_loop`)
   only advances state on the process that has an `engine` set. If more
   than one worker/instance serves traffic, "load" and the live
   WebSocket can land on different processes -- the one serving the
   WebSocket may never see `state.engine` set, so its tick loop
   perpetually no-ops. `render.yaml`'s `startCommand` doesn't set
   `--workers`, so this would only occur if the deployed instance count/
   worker count was set to >1 some other way.
2. **(Can't rule out without logs)** Render idle-throttling of the
   background asyncio task between requests.

Separately confirmed, real, distinct finding: `sensor_is_reporting`
(`run_data.py:59-60`) returns `False` -- mapped to RED -- both when a
sensor has gone stale AND when it simply hasn't reported yet because
simulated time hasn't reached it. These are different states and the UI
doesn't currently distinguish them.
