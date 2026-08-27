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

## Task 2 — replay/Play bug ✅ (leading cause addressed; RED-conflation fixed)

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

**RED-conflation finding: fixed, with explicit approval.** Added
`SensorHealth.NOT_YET_REPORTING` (`replay/models.py`) distinct from `RED`:
`RunData.sensor_is_reporting` (`replay/run_data.py`) now returns
`SensorHealth` directly instead of `bool | None`, returning
`NOT_YET_REPORTING` when no telemetry row exists yet for a station instead
of folding that into `RED`. `replay/engine.py`'s `current_state()` was
simplified accordingly (no longer needs its own None/bool-to-enum
mapping). Per this project's own rule ("tests are the spec, stop and
ask"), the user was asked before touching the existing assertion in
`tests/unit/test_replay.py::test_station_without_sensors_reports_not_applicable_never_red`
and explicitly approved adding the new state; that assertion was widened
to include `NOT_YET_REPORTING`, and a new dedicated regression test,
`test_instrumented_station_reports_not_yet_reporting_before_first_reading`,
asserts the specific case directly (using ST-03, the second instrumented
station, since ST-01 already has a reading at the run's start time).
Frontend: `state/types.ts`'s `SensorHealth` union gained
`"not_yet_reporting"`; `scene/Station3D.tsx`'s sensor lamp now renders it
as a tetrahedron in the same neutral color as `NOT_APPLICABLE` (neither is
a fault, so neither earns a beacon color -- shape is what keeps them
distinguishable, same rule as `NOT_APPLICABLE`'s octahedron).

## Task 3 — Serpentine layout ✅

Replaced the 328m straight ruler (every station at `y_m: 0.0`, uniform 8m
spacing) with a 3-row serpentine (S-shaped) plant footprint in
`scripts/gen_example_42.py`'s `build_line()`/new `build_layout()`. Only
that one function changed -- `build_station()` untouched, so all 42
station ids, zones, sequence order, sensors, commissioning baselines,
inspection flags, and cost/value-add figures are byte-identical to
before. Confirmed via `git diff`: the regenerated
`data/lines/example_42.yaml` differs from the previous version in exactly
one hunk, entirely inside the `layout:` block.

Layout: each zone is its own row (`y_m`: body=0, paint=-22, final=-44),
so the three bays are visually separable by geometry alone. Direction
alternates row to row (body left-to-right, paint right-to-left, final
left-to-right again -- the two "turns" that make it an S), and intra-row
spacing follows a per-zone formula instead of a uniform gap: body cycles
6.0/7.5/9.0/10.5m, paint cycles 8/10/12m, final cycles
5.0/6.2/7.4/8.6/9.8m. Every `distance_m` is computed as the actual
Euclidean distance between its two coordinates, never set independently
-- the zone-transition segments (ST-16→ST-17: 22.56m, ST-26→ST-27:
23.41m) come out longer than any in-row gap purely because a transition
is a full row-to-row corridor turn, not because a number was hand-picked.

Added `test_example_42_segment_distances_match_actual_geometry` to
`tests/unit/test_config.py`, asserting that invariant for all 41 segments
in the real `example_42.yaml` -- this is the kind of thing that silently
drifts if a layout is ever hand-edited instead of regenerated.

Regenerating the golden insert-at-17 fixture
(`tests/golden/config/example_42_after_insert_at_17.yaml`, approved with
diff shown first) turned out to be self-consistent for free:
`insert_station`'s midpoint math (`specs.py:280-287`) places the new
station exactly halfway between its neighbours, and a midpoint's distance
to each endpoint is always exactly half the endpoint-to-endpoint
distance, so the split segments (ST-16→ST-43: 11.28m, ST-43→ST-17:
11.28m) satisfy the same real-geometry invariant automatically.

**Second, larger blast radius found and fixed, with explicit approval:**
`datagen/writer.py`'s `simulate_run` computes each car's conveyor transit
time as `distance / config.conveyor_speed_mps` (`writer.py:177-178`), so
changing segment distances changes every downstream telemetry/event
timestamp in any run generated over `example_42.yaml` -- not just the
`LineSpec` itself. This broke `tests/golden/test_datagen_golden.py`
(the 400-car run's `ground_truth.json`, documented in that test's own
docstring as "the answer key every later prompt's Predict/Trace
correctness gets graded against"), and left two more things stale:
`backend/data/runs/default_400_car_run/` (the pre-generated run committed
for Render's startup safety net -- confirmed byte-identical to the golden
fixture before this fix) and the trained `data/models/risk_v1` (built
from runs generated over the same line file).

Fixed by regenerating all three from the new layout, in this order:
`python -m lineage.datagen.cli` (rewrites
`data/runs/default_400_car_run/{telemetry,events,inspection}.csv` and
`ground_truth.json`), copying the new `ground_truth.json` over the frozen
golden fixture, then `scripts/train_risk_model.py` to retrain `risk_v1`.
Diff-reviewed before finalizing: only timestamps shifted (by single-digit
to tens of seconds, from the new transit times) -- every defect id,
mechanism, origin/detection station, exposed car list, and detection
outcome in `ground_truth.json` is unchanged. `tests/golden/test_spc_golden.py`
and `tests/golden/test_trace_golden.py` were never at risk: they assert
behavioral properties (SPC fires within a seeded car-index window, alarm
rates) against a freshly-generated run each time, not a byte-frozen file.

Notable, reassuring result: the retrained `risk_v1` model came out
**byte-identical** to what was already committed. Its features are all
relative to per-station sensor baselines (z-scores, deviation from
nominal), not absolute conveyor geometry or wall-clock timestamps, so a
layout change that only shifts timing doesn't touch what the model
actually learns from.

Verified: `pytest -q` 140/140 (137 baseline + 1 new invariant test + 1
new NOT_YET_REPORTING regression test from Task 2, plus the datagen
golden test this task temporarily broke and then fixed), `ruff check .`
clean, `npx playwright test` 7/8 (same pre-existing, documented
spawn-tray failure, unrelated to this change).

## Task 4 — Design tokens ✅

Replaced the two-source-of-truth setup (`styles/colors.ts`'s JS hex values
kept in sync with `styles/tokens.css`'s `:root` block only by a comment
asking nicely) with one real source: `styles/tokens.ts`. It exports
`PALETTE`/`FONT_FAMILIES`/`TYPE_SCALE` (unchanged values, moved), a new
`SPACING` scale (`--space-1`…`--space-12`, one step = 0.25rem) and
`WIDTHS` set (the three recurring panel widths), and
`applyDesignTokens()`, called once from `main.tsx`, which injects all of
it as CSS custom properties on `:root` -- `tokens.css` no longer hardcodes
a second copy of any value, just the structural rules (`.eyebrow`,
`.data`, `.hazard-hatch`) that read `var(--...)`. `colors.ts` is deleted;
its three importers (`Scene.tsx`, `Car3D.tsx`, `Line3D.tsx`) and
`Station3D.tsx` now import `PALETTE` from `tokens.ts` directly, since
three.js materials still need real hex values, not CSS custom properties.

Full status vocabulary defined once, covering all four backend enums
(`SensorHealth`, `MachineHealth`, `SPCState`, `RiskLevel` -- "environment
validity" is `SPCState.ENVIRONMENT_INVALID`, not a separate backend
concept): each state maps to `{ color, shape, label }` via
`SENSOR_HEALTH_TOKENS`/`MACHINE_HEALTH_TOKENS`/`SPC_STATE_TOKENS`/
`RISK_LEVEL_TOKENS`. One 5-shape vocabulary is reused across all four so
shape carries a single consistent meaning everywhere: circle=healthy,
triangle=caution, diamond=fault, hexagon=pending/no-data-yet,
ring=not-applicable/unknown -- colour is never the only signal, so the
distinction survives a projector or a colour-blind viewer. `SPCState`/
`RiskLevel` TS types added to `state/types.ts`; nothing in the frontend
surfaces them yet (no endpoint returns them today), so their tokens are
defined and ready but unused until Task 6/7 wires up a real view.

`Station3D.tsx` refactored to consume the tokens instead of its own local
`sensorColor`/`machineColor`/`sensorGeometryFor` -- both lamps (sensor and
machine) now render shape from the shared vocabulary via one
`StatusLamp`/`ShapeGeometry` helper. This is also a real fix, not just a
refactor: `MachineHealth`'s lamp used to be a fixed cube regardless of
state (colour-only, failing the colour-blind/projector requirement); it's
now circle (green) vs. diamond (red), same as sensor health.

New `components/StatusBadge.tsx` (filled in an existing empty stub file
that had never been wired up) renders a token as glyph + colour + label
text -- wired into the three 2D spots that used to render
`sensor_health`/`machine_health` as bare unstyled text
(`OperatorView`/`FloorSupervisorView`/`PlantManagerView`), so the
NOT_YET_REPORTING/RED distinction from Task 2 is now actually visible
somewhere in 2D, not just in the 3D Mirror's lamp shape. Verified visually
(Playwright screenshot + DOM text extraction) against the live default
run: ST-41/ST-42 (end of line, simulated time hasn't reached them) show
"⬡ No Data Yet", seeded-defect stations show "◆ Sensor Fault", manual
stations show "○ No Sensor" -- three distinct glyphs and labels, not a
shared "unknown" fallback.

Every literal spacing/width value across `TopBar`, `StationPanel`,
`CarPanel`, `StationBuilder`, `StationBuilderForm`, `OperatorView`,
`FloorSupervisorView`, `LeadershipView`, `PlantManagerView`,
`PredictionLedgerView` replaced with `var(--space-N)`/`var(--width-*)`.

Verified: `pytest -q` 140/140 (unaffected, frontend-only change),
`ruff check .` clean, `tsc --noEmit` clean, `vitest run` 1/1, production
build succeeds, `npx playwright test` 7/8 (same pre-existing, documented
spawn-tray failure), plus a manual Playwright-driven visual check of the
Mirror (serpentine layout + lamp shapes) and the Operator/Floor Supervisor
views (status badges) against the running dev server.

## Remaining tasks

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

Separately confirmed, real, distinct finding (now fixed, see Task 2's
RED-conflation writeup above): `sensor_is_reporting` (`run_data.py`) used
to return `False` -- mapped to RED -- both when a sensor had gone stale
AND when it simply hadn't reported yet because simulated time hadn't
reached it. These are different states; the UI now distinguishes them via
`SensorHealth.NOT_YET_REPORTING`.
