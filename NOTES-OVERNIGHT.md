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

## DESIGN.md added

The design plan behind Tasks 1-4 was approved in conversation during
Prompt A and never written down -- it got lost to context compaction
partway through this branch. Added `DESIGN.md` at repo root as the
durable fix: palette/type/status vocabulary documented from what's
already implemented in `styles/tokens.ts`, and the Mirror wireframe,
Builder wireframe, node anatomy, and signature element (none of which
existed in any file) proposed fresh and approved before Task 5's rebuild
started. Tasks 6 and 8 should cite `DESIGN.md`, not "the approved plan."

## Task 5 — 3D Mirror rebuild ✅

Rebuilt `Station3D.tsx`, `Line3D.tsx`, `Scene.tsx`, `Car3D.tsx` per
`DESIGN.md`.

**Signature element:** the beacon mast. Station lamps moved from sitting
directly on the block roof to the top of a thin mast rising above it. A
station in a fault state now also emits a light beam rising further into
the sky -- and per explicit direction, the two fault beams are
deliberately distinct, not the same red column with a different label:
a sensor fault gets a narrow, steady cone (`SensorFaultBeam`); a machine
fault gets a wider, tapered cylinder pulsing via `useFrame`
(`MachineFaultBeam`). Colour is never the only signal, one level up from
the lamp shapes themselves. Verified visually against the live default
run (screenshot): masts, lamp clusters, and a lit fault beam all render
as designed.

**Zone identity:** floating `BODY`/`PAINT`/`FINAL` text labels added
above the first station of each zone's row (`Line3D.tsx`'s
`zoneLabelPositions`), on top of the row-separation geometry from Task 3
-- verified in the same screenshot.

**Hover tooltip:** `Station3D.tsx` now tracks hover state and renders a
`drei` `Html`-anchored tooltip reusing the actual `StatusBadge` component
(not a reimplementation) plus latest readings. Required threading
`stationName` and `latestReadings` through as new `Station3D` props from
`Line3D.tsx`. Verified via a precise computed-position hover (DOM text
extraction confirmed real badge/label content renders).

**Follow mode:** clicking a car already engaged follow mode, but there
was no visible indication it had happened and no way back to free orbit.
Added `FollowIndicator` in `Scene.tsx` -- a "Following CAR-XXXXX · Stop"
overlay, calling the existing `followCar(null)` action. Verified live: a
car click amber-highlights the followed car, the indicator appears, and
Stop clears it.

**Car-click raycasting bug -- diagnosed and fixed, confirmed distinct
from the earlier occlusion issue.** Root cause (full diagnosis in
`DESIGN.md`): `InstancedMesh.raycast()` broad-phase-rejects against
`this.boundingSphere`, cached once on the *first* raycast call from
whatever instance transforms existed at that moment, and never
recomputed as `Car3D`'s `useFrame` moves every instance every frame --
so it silently missed every subsequent click and hover, on every car,
always. Confirmed empirically: a paused-replay, pixel-precise hover sweep
across the car's own bounding box produced zero hits anywhere, ruling
out an occlusion/z-order theory before it ruled anything in; adding
`mesh.computeBoundingSphere()` once per frame (`Car3D.tsx`) fixed it
immediately, verified via a real click opening `CarPanel`. This is a
sibling of the earlier `frustumCulled={false}` fix (same three.js gotcha
-- a per-object cached bounding volume ignoring per-instance updates),
not the same bug resurfacing: that one is `Object3D`'s own bounding
sphere for render-time frustum culling; this is
`InstancedMesh.raycast()`'s separate cached sphere for hit-testing.

**Regression guard, deliberately hard to defeat:** added "clicking a car
opens its panel (raycast regression guard)" to `e2e/smoke.spec.ts`. It
clicks a car's exact screen-projected position while replay is actively
*playing* (never paused) -- a paused-replay test would still pass if
`computeBoundingSphere()` were deleted, since a stationary car's
stale-at-mount bounding sphere still happens to cover wherever it's
stopped. Verified the guard actually guards: manually deleted the
`computeBoundingSphere()` call, confirmed the new test fails (and only
that test), restored the call, confirmed it passes again.
`camera`/`renderer` added to `window.__lineageTest` (`testHooks.ts`) so
the test can compute the car's exact screen pixel rather than guessing.

Verified: `pytest -q` 140/140 (unaffected), `ruff check .` clean,
`tsc --noEmit` clean, `vitest run` 1/1, production build succeeds,
`npx playwright test` 8/9 (was 7/8: +1 new regression test passing; same
pre-existing documented spawn-tray gap, unrelated).

## Task 6 — Role views ✅

Investigation before writing anything turned up more than a frontend
rebuild: `predict/bottleneck.py`'s `forecast_line` is fully built and
tested (bottleneck warnings need zero new logic, just wiring), but
`api/routes/act.py` and `api/routes/trace.py` are both empty stub files
-- their routers aren't even registered in `app.py`. Act and Trace have
zero HTTP surface today, even though `act/proposals.py`, `act/ledger.py`,
`act/validator.py`, `trace/rootcause.py`, and `trace/lineage_query.py`
are all built and unit-tested. Floor Supervisor's "approve Act
proposals" and Plant Manager's "recurring root causes from Trace" both
require standing these up for the first time, not just calling them.
`act/models.py` already encodes `MINIMUM_APPROVER_ROLE = FLOOR_SUPERVISOR`
-- the role-gating for approval is correct by construction, already.

**Approved, deliberate spec change:** `test_plant_manager_view_includes_summary_counts`
asserted `"line_state" in body`. Task 6 wants Plant Manager to be
weekly/non-live with no real-time firehose, which means removing that
field -- a real contract change, approved explicitly before touching the
test (same precedent as Task 2's `NOT_YET_REPORTING`).

### Operator ✅

Backend (additive only, no existing field touched): `OperatorView`
gained `spc_verdict: SPCVerdict | None`, the station's live control state
evaluated via the real, already-tested `evaluate_spc` -- not a new
heuristic. Required two new additive `RunData` methods
(`reading_history_at`, `shift_changes_at`) to get an ordered reading/
shift-change history up to "now", and reconstructing ambient temperature
live from the run's own config (`baseline_temp_c` + zone excursions,
keyed by the car the most recent reading belongs to) rather than
assuming a neutral value -- `telemetry.csv` never persists `ambient_c`
per row, it's a generation-time input, not a recorded quantity, so this
was worth getting right rather than faking. New test
`test_operator_view_includes_live_spc_verdict` asserts a real, non-UNKNOWN
verdict once telemetry exists, not merely a present-but-empty field.

Frontend: sensor/machine health via `StatusBadge` (already there),
handover status and calibration state added via the new `spc_verdict`
field (`SPC_STATE_TOKENS`), and a new handover checklist -- client-side,
localStorage-persisted per station (no persistence requirement was
specified for it, so no new endpoint), remounted with a `key` per
station so switching stations never leaks a previous station's checked
items, and auto-resets on a real backend-detected handover
(`recalibrating` false->true transition), not just whenever the
component happens to remount. Verified: checking an item persists across
reload, and does not carry over when switching stations.

Playwright: strengthened "Operator shows exactly one station" to assert
two Operator-only elements (`Handover status:`, `Handover checklist`)
that exist in no other role view, on top of the existing row-count check.

Verified: `pytest -q` 141/141 (+1 new test), `ruff check .` clean,
`tsc --noEmit` clean, `vitest run` 1/1, production build succeeds,
`npx playwright test` 8/9 (same pre-existing documented spawn-tray gap).

### Floor Supervisor ✅

Backend: `api/routes/act.py` wired up for the first time (was an empty
stub, router not even registered in `app.py`) -- `GET /api/act/proposals`
generates proposals lazily from the run's real failed inspections
(`inspection.csv` `result == "fail"`, traced via the already-tested
`trace.lineage_query.trace` then `act.proposals.propose`), cached on
`AppState` like the prediction ledger; `POST /api/act/proposals/{id}/approve`
writes to a new `AppState.audit_ledger` via the already-tested
`act.ledger.approve`, always as `ApproverRole.FLOOR_SUPERVISOR` --
`act/models.py`'s `MINIMUM_APPROVER_ROLE` is already exactly that, so this
endpoint can't be used to approve as a lower role because there's no
other endpoint that would let it. `FloorSupervisorView` gained
`spc_alarms` (every station currently OUT_OF_CONTROL/ENVIRONMENT_INVALID,
reusing Operator's `_live_spc_verdict`), `high_risk_cars` (cars currently
on the line, `assess_risk` against their next inspection station --
`predict.bottleneck.forecast_line` was already built and tested, needed
only wiring), and `issue_assignments` (a minimal in-memory
`issue_id -> operator_id` record via two new endpoints, not a real
auth/session system). All additive; no existing field removed.

**A real bug found and fixed along the way, not scope creep:** `seek`
never touched `snapshot_history`, so a seek immediately followed by any
role-view poll (exactly what scrubbing the replay position does) could
read a stale pre-seek snapshot for up to a second -- the background tick
loop is the only other thing that ever pushes a snapshot, and only while
playing. Caught because it made the new Floor Supervisor tests flaky
against a real seeded scenario (ST-06's torque drift), not by inspection.
Fixed by having `seek` push its own returned state into `snapshot_history`
immediately (`api/routes/mirror.py`).

**Perf, measured, not assumed:** the new fields' first pass cost ~2.9s
per request against a 2-hours-in 400-car run (`_spc_alarms`'s 42x live
`evaluate_spc` calls dominating, each re-filtering the full,
ever-growing telemetry/events frames from scratch). Fixed by grouping
`RunData`'s telemetry/events by station once at construction
(`_telemetry_by_station`/`_events_by_station`), so per-station queries
filter only that station's own slice -- ~4-5x faster (down to ~0.6-0.9s),
verified before and after. The remaining cost is dominated by
`engine.current_state()`'s own per-tick scan, which is the separate,
already-flagged RunData/build_features scan-cost task from before this
branch started -- not fixed here, out of scope for Task 6.

Frontend: `FloorSupervisorView` now embeds the actual `<Scene />` (the
Mirror) alongside the alert queue, per "the Mirror plus a live alert
queue" -- split layout, Mirror on the left, a scrollable panel on the
right with SPC alarms / high-risk cars / bottleneck warnings / pending
Act proposals, each alert with an assign-to-operator control reusing the
same component. Verified live end-to-end against the real seeded
default run: 19-21 real SPC alarms, 9 real high-risk cars with sane
stations-remaining counts, 15 real bottleneck warnings with real
minutes-to-onset, 57 real Act proposals citing real trace evidence;
assign/unassign and approve all round-trip correctly (approve confirmed
via poll: pending count actually decrements).

New `tests/unit/test_api_floor_supervisor.py` (module-scoped fixture,
same real-default-run pattern `test_spc_golden.py` uses, not a synthetic
tiny line -- these features need real telemetry/inspection history to
prove the wiring, not just the response shape) covers the new alert-queue
fields against the known ST-06 torque-drift scenario, the assignment
endpoints round-tripping, and Act proposals listing/approving/404.

Playwright: Floor Supervisor's assertion now also checks for the
SPC alarms / high-risk cars / bottleneck warnings section headers --
Floor-Supervisor-only content no shared fallback could produce.

Verified: `pytest -q` 145/145 (+4 new tests), `ruff check .` clean,
`tsc --noEmit` clean, `vitest run` 1/1, production build succeeds,
`npx playwright test` 8/9 (same pre-existing documented spawn-tray gap).

### Plant Manager ✅ (Task 6 complete)

Real contract change, approved before touching it: `line_state` and the
live `LineSummary` are both gone -- Task 6 is explicit that Plant Manager
is "weekly, not live, no real-time firehose," and a live-computed summary
(occupied stations *right now*) contradicts that just as much as the
full per-station table did. Replaced with five weekly aggregates,
computed over the whole run to date from `inspection.csv` and the twin
store, not a live tick:

- `defect_rate_by_station` / `defect_rate_by_zone`: grouped straight from
  `inspection.csv`'s real `result` column -- zone totals are the sum of
  their member stations', checked in the new test, not just plausible.
- `rework`: distinct cars with >=1 failed inspection vs. total inspected.
- `recurring_root_causes`: every real failed inspection traced back to
  its likely origin (`trace.lineage_query.trace`), aggregated by
  originating station, sorted by occurrence. Shares its trace pass with
  Act's proposal generation via a new `AppState.trace_results` cache and
  `trace.lineage_query.traced_failures` -- both features need the exact
  same, real per-car work, now computed once instead of twice.
- `maintenance_status`: schedule (from `StationSpec.machine` +
  `RunData`'s new `days_since_maintenance_at`) reported *alongside*
  predicted need (mean `machine_wear_state` across each station's most
  recent visits), not collapsed into one score -- so "schedule says fine,
  wear says otherwise" (or the reverse) stays visible rather than hidden
  behind a single number.

Verified live against the real seeded default run: defect rates land
exactly on the three real inspection stations (ST-16/26/42); recurring
root causes correctly surfaces ST-02 as the single largest source (182
occurrences) -- confirmed this is real, not a bug: ST-02 is the seeded
*unflagged* operator-handover station, so its bias never gets the
recalibration-window pass a flagged handover would, and it affects every
car in that operator's ~200-car shift, correctly dwarfing the 30-car-wide
torque-drift window at ST-06 (27 occurrences). One maintenance-status
value was legitimately negative (`days_since_maintenance` for a station
whose commissioning date happens to fall after this short demo run's
simulated window, since `last_maintenance_date` is spread across all 12
months of 2024 in the sample data) -- a real property of the existing
sample line, not a bug, and the new test was corrected to allow it
rather than the app changed to hide it.

Frontend: no auto-polling (unlike every other role view) -- a manual
"Refresh" button instead, reinforcing "a report you pull, not a feed you
watch." No live per-station sensor/machine/buffer table anywhere.

New `tests/unit/test_api_plant_manager.py` (same real-default-run
pattern as Floor Supervisor's) covers the response shape, defect-rate/
rework arithmetic, the ST-02/ST-06 recurring-root-cause result, and
maintenance status across every station. Playwright's Plant Manager
assertion now checks for the recurring-root-causes and maintenance
sections and explicitly asserts no "Sensor" column exists anywhere on
the page.

Verified: `pytest -q` 149/149 (+4 new tests), `ruff check .` clean,
`tsc --noEmit` clean, `vitest run` 1/1, production build succeeds,
`npx playwright test` 8/9 (same pre-existing documented spawn-tray gap).

## Task 7 — Leadership ROI ✅

Zero existing backend logic to build on: `StationSpec.cost_per_hour`/
`value_add_pct` existed but were read by nothing anywhere in the
backend before this. Real, approved contract change (same class as
Task 6's Plant Manager one): the old live occupied/alarm/buffer
`LineSummary` triple is gone -- `LineSummary`/`_summarize` are now fully
dead code, deleted rather than left as unused clutter. Replaced with:

- `total_cost_per_hour` / `total_value_added_cost_per_hour` /
  `value_added_ratio`: a real, standard lean-manufacturing metric
  (value-add-weighted cost, summed across all 42 stations), not
  fabricated.
- `cost_by_zone`: the same breakdown by zone, mirroring Task 6's
  `defect_rate_by_zone` pattern.
- `sensor_retrofit_candidates`: manual (no-sensor) stations only,
  ranked by recurring defect occurrences first, then economic weight
  (`cost_per_hour * value_add_pct`). Reuses Task 6's
  `_ensure_trace_results` cache directly -- a manual station implicated
  often as a real traced defect origin is a genuine, data-backed retrofit
  signal. Deliberately does **not** fabricate a dollar "ROI" figure: there
  is no cost-per-defect input anywhere in the data model to compute one
  from, and inventing one would violate "predictions/numbers reflect real
  available info."

Verified live and in `tests/unit/test_api_leadership.py` (same
real-default-run pattern as Tasks 6's Floor Supervisor/Plant Manager
tests) against the real seeded default run: ST-02 (the seeded unflagged
operator-handover station, already found to be the largest recurring
root cause in Task 6) correctly ranks first among retrofit candidates,
reusing that exact same real data rather than a coincidence. Zone cost
totals checked to equal the sum of their member stations', not just
plausible numbers.

Frontend: cost/value-add totals, zone breakdown, and the ranked
retrofit-candidates table replace the three counters. Playwright's
Leadership assertion now checks for this real content and confirms no
live per-station sensor/machine table exists anywhere on the page (the
retrofit table is curated business data, not live status -- that
distinction, not "zero tables", is the actual invariant).

Verified: `pytest -q` 152/152 (+3 new tests), `ruff check .` clean,
`tsc --noEmit` clean, `vitest run` 1/1, production build succeeds,
`npx playwright test` 8/9 (same pre-existing documented spawn-tray gap).

## Task 8 — Node-graph Builder canvas ✅

Backend groundwork first, before any UI: `LineSpec` gained four new
mutation primitives in `config/specs.py`, each constructing a fresh
`LineSpec` via the class constructor (never `model_copy(update=...)`,
which silently skips Pydantic v2 validators even with
`revalidate_instances="always"` — that setting only governs re-validation
when a model is *nested as a field*, not what `model_copy` itself does):

- `prepend_station`: inserts before the current first station,
  extrapolating both the new layout coordinate and the new conveyor
  segment's distance backward along the line's existing direction —
  `insert_station` has no "insert at head" (its `after_station_id=None`
  always means tail-append).
- `set_segment_distance`: rescales one segment to an authoritative
  `distance_m`, deriving the coordinate from the distance (never the
  reverse). Rigidly translates the *entire downstream station chain* by
  the resulting delta, not just the one adjacent station — moving only
  the adjacent station would silently invalidate the next segment's own
  distance the moment the path isn't perfectly straight. Verified against
  both a synthetic L-shaped fixture and the real serpentine
  `example_42.yaml`.
- `replace_station`: swaps a station's own fields (sensors, baseline, ...)
  in place, keeping position/topology untouched, re-validating the whole
  line so cross-station invariants (duplicate sensor ids, etc.) still run.
- `with_environment_envelope`: replaces the line-wide envelope.

Real bug found and fixed along the way, in the *pre-existing*
`remove_station`: it summed the two adjacent segments' distances to
rejoin the gap, correct only when the removed station was collinear with
its neighbours — it silently overstated the true distance at any turn (a
zone-transition corner). Fixed to compute the actual Euclidean distance
between the two surviving neighbours' unchanged coordinates. Confirmed
empirically against `example_42.yaml`: removing a station at a real
corner produced exactly one geometry-invariant violation under the old
code, zero under the fix; a straight-run removal was unaffected either
way, and the existing collinear-fixture test kept passing unchanged (a
correctness fix, not a behaviour change any test asserted — no "stop and
ask" gate applied).

New `api/routes/builder.py` endpoints wire all of this up: `POST
.../stations/prepend`, `PUT .../stations/{id}/sensors`, `PUT
.../stations/{id}/commissioning_baseline`, `PUT .../segments/distance`,
`PUT .../environment_envelope`, and `POST .../commissioning/run_to_learn`
(a standalone endpoint, independent of any draft). `run_to_learn` lives in
a new `config/commissioning.py`: given a rough nominal idle/loaded centre
per quantity and each sensor's own `accuracy_class`, it draws real
`numpy` random samples and computes genuine mean/std from them — a
simulated capture, clearly labelled as such, but never a fabricated
number.

One existing-test-breaking change, flagged and approved before
implementing (per the "tests are the spec, stop and ask" rule): the
Builder's move-up endpoint used to hard-reject moving a station into the
first position at all (`insert_station` has no "insert at head").
`prepend_station` now makes that actually work — approved, and the two
tests that asserted the old 400 (`test_move_station_up_and_down`,
`test_move_first_station_up_returns_400`) were updated to assert the new
success behaviour instead, not silently patched around.

Frontend: `@xyflow/react` (approved new dependency) replaces the old
form-based Builder entirely — `StationBuilder.tsx`/`StationBuilderForm.tsx`
deleted, not left as dead code. New `builder/graph/` module: `StationNode`
(zone-identity stripe via a new `ZONE_TOKENS` set — the Mirror's zone
identity comes from row position, not a hue, so the flat 2D canvas needed
its own token; sensor indicator reuses `SENSOR_HEALTH_TOKENS.not_applicable`
for "no sensor" specifically, since that's its real documented meaning,
never a live "Reporting" claim a config-time draft has no run to back
up), `SpawnTray` (bottom-right per an explicit live override of
`DESIGN.md`'s original left-tray sketch, updated there to match),
`StationCreateModal`, `PropertiesPanel` (sensors/distance/baseline),
`CommissioningWizard` (enter-known-values and run-to-learn paths), and
`EnvironmentEnvelopeEditor`. Drag-from-tray-onto-a-link inserts (splitting
that segment); drag onto either end prepends/appends; dragging between
two nodes' ports reorders by composing the already-tested remove +
insert-after primitives client-side (no new backend endpoint needed);
clicking a link cuts it by removing its downstream station. `findDropTarget`
(pure hit-testing against each link's real endpoint positions, tray-drop
resolution) has its own `vitest` suite.

Real, found-in-testing bug: `fitView`'s default `minZoom` (0.5) can't
fit all 42 stations in a normal viewport, leaving most of them
positioned off-screen — not just a test inconvenience but a genuine "half
the line is invisible" UX bug. Fixed by lowering `minZoom` so `fitView`
can actually zoom out far enough. Also fixed: the properties panel used
to stretch full-height, covering the spawn tray (same bottom-right
corner) whenever a node was selected — now height-capped instead.

Save writes the new `LineSpec` to disk (unchanged `POST .../save`), then a
new `POST .../activate` swaps it in as `state.line` — the Mirror's actual
live line — resetting every cache that was built against the *previous*
line (`engine`, `genealogy_store`, `prediction_ledger`, `trace_results`,
`act_proposals`, `issue_assignments`, `snapshot_history`), mirroring
exactly what `mirror.py`'s own `load` action already does when swapping
runs. `audit_ledger` is deliberately left alone, same reasoning as `load`.

This closes the pre-existing Playwright spawn-tray gap (the 9th test,
failing since the harness was built) and adds three more: tray → insert
mid-line lands the new station at the correct sequence position, cutting
a link, and adding a sensorless manual station without it erroring.
Native HTML5 drag-and-drop isn't drivable through Playwright's
mouse-based helpers (no real OS-level drag under automation), so these
dispatch the actual `dragstart`/`dragover`/`drop` sequence with a real
`DataTransfer` — exercising the app's real handlers, not a shortcut.

Verified: `pytest -q` 182/182 (+18 new tests: `test_config.py` 32/32,
`test_api_builder.py` 30/30), `ruff check .` clean, `tsc --noEmit` clean,
`vitest run` 6/6 (+5 new), production build succeeds, `npx playwright
test` 12/12 (the long-standing 9th test now passes, +3 new).

## Task 9 — Final sweep ✅

### Gate, run fresh, full

`pytest -q` 182/182 · `ruff check .` clean · `tsc --noEmit` clean ·
`vitest run` 6/6 · production build succeeds · `npx playwright test`
12/12. All six green, nothing skipped or weakened to get there.

### Screenshots

`screenshots/` (project root), captured against a live-playing
`default_400_car_run` at 60x so Mirror/role views show real, non-empty
data, not a frozen initial state:

- `01-mirror.png` -- the 3-row serpentine, zone labels, cars in transit.
- `02-operator.png` -- ST-01, live SPC verdict, handover checklist.
- `03-floor-supervisor.png` -- live alert queue (CAR-00000 correctly
  flagged high-risk en route to ST-16, matching the seeded scenario).
- `04-plant-manager.png` -- weekly defect-rate/rework/root-cause report
  (ST-16/26/42 fail rates, ST-02 leading recurring root causes -- same
  seeded torque-drift/unflagged-handover data every earlier task verified
  against).
- `05-leadership.png` -- real cost/value-add ROI numbers, ST-02 ranking
  first among retrofit candidates (consistent with Plant Manager's and
  Task 7's own findings, not a coincidence -- same underlying trace data).
- `06-builder.png` -- the node-graph canvas, spawn tray bottom-right,
  save/activate panel.

### Merge

`main` had not moved since `feat/ui-overhaul` branched from it
(`git merge-base main feat/ui-overhaul` == `main`'s own tip, `01bd81f`) --
a clean fast-forward, zero conflicts, nothing to resolve. Merged and
pushed to `origin/main` at `3dfa1f8`.

### What landed, all nine tasks

1. Playwright harness -- 8 initial smoke tests, one (spawn tray) left
   deliberately failing and documented until Task 8 could close it.
2. Replay/Play bug -- leading suspected cause (multi-worker `AppState`
   global) addressed defensively (`render.yaml` pins `--workers 1`,
   documented inline); a real, distinct, *confirmed* bug (RED/
   NOT_YET_REPORTING conflation) found and fixed alongside it.
3. Serpentine layout -- real 3-row S-shaped plant footprint replacing the
   328m straight ruler; three golden artifacts regenerated with approval.
4. Design tokens -- single source of truth (`styles/tokens.ts`) replacing
   a hand-synced JS/CSS pair.
5. 3D Mirror rebuild -- per `DESIGN.md`; real car-click raycasting bug
   (stale `InstancedMesh.boundingSphere`) diagnosed and fixed.
6. Role views -- Operator/Floor Supervisor/Plant Manager rebuilt on real
   backend logic (Act/Trace stood up from unregistered stub routers); a
   real seek/snapshot-staleness bug and a real per-request perf issue
   found and fixed along the way.
7. Leadership ROI -- real cost/value-add metrics and a data-backed sensor-
   retrofit ranking; no fabricated dollar figure.
8. Node-graph Builder canvas -- full React Flow rebuild; a real
   `remove_station` geometry bug found and fixed; closes the Task-1 spawn-
   tray gap plus three new Playwright tests.
9. Final sweep -- this section.

### What didn't land, and why

- **Task 2's leading root cause was never independently confirmed.** No
  Render production logs were available in this offline session, so the
  multi-worker-global theory got a defensive fix (`--workers 1`, with an
  inline comment explaining exactly why raising it isn't safe without
  moving `AppState` out of an in-process global first) but not a
  postmortem-grade confirmation. If the original symptom (replay looking
  stuck) recurs in production, that pin is the first thing to double-
  check is actually in effect, and Render's own logs are the next place
  to look -- alternative #2 (idle-throttling of the background asyncio
  task) was never ruled out either, for the same reason.
- **The `NOTES-OVERNIGHT.md` diagnosis block this replaces was stale and
  self-contradicting**, caught while writing this section: it claimed
  "`render.yaml`'s `startCommand` doesn't set `--workers`", written
  before Task 2's own fix landed and never updated after -- `render.yaml`
  has pinned `--workers 1` since Task 2. Corrected here rather than left
  to mislead the next reader.
- **The RunData/build_features scan-cost item** (see its own section
  below) -- explicitly out of scope for every task that touched adjacent
  code, including this one.

### Golden files regenerated (all, with approval shown first each time)

1. `tests/golden/config/example_42_after_insert_at_17.yaml` (Task 3) --
   turned out self-consistent for free, since `insert_station`'s midpoint
   math keeps the same real-geometry invariant automatically.
2. `tests/golden/datagen`'s `ground_truth.json`, `backend/data/runs/
   default_400_car_run/{telemetry,events,inspection}.csv` +
   `ground_truth.json`, and `data/models/risk_v1` (Task 3) -- the
   serpentine layout changes segment distances, which changes every
   downstream transit-time timestamp in any run generated over
   `example_42.yaml`. Diff-reviewed before finalizing: only timestamps
   shifted; every defect id/mechanism/station/outcome is unchanged.
   `risk_v1` came back byte-identical on retrain (its features are all
   relative z-scores, not absolute timing).

### Approved contract breaks (all, "tests are the spec, stop and ask" honored each time)

1. Task 2: `SensorHealth.NOT_YET_REPORTING` added; the existing
   `test_station_without_sensors_reports_not_applicable_never_red`
   assertion widened to include it.
2. Task 6: Plant Manager's `line_state` field and the live `LineSummary`
   removed (Task 6 is explicit that Plant Manager is weekly, not live);
   `test_plant_manager_view_includes_summary_counts` updated accordingly.
3. Task 7: `LineSummary`/`_summarize` deleted outright as the now-fully-
   dead code that change left behind.
4. Task 8: the Builder's move-up endpoint used to hard-reject moving a
   station into the first position; `prepend_station` now makes it work,
   and the two tests that asserted the old 400 were updated to assert
   success instead.

### What to check by eye before trusting the merge

- `screenshots/06-builder.png`: the zone-identity stripe on each node is
  real but subtle at the zoom level 42+ stations forces `fitView` down
  to -- worth a live zoom-in to confirm the three zone colours (steel-
  blue/violet/bronze) actually read as distinct, not just "different
  greys" on your monitor.
- The Mirror's beacon-glow fault treatment (Task 5's signature shot) isn't
  in any of the six screenshots -- none was captured mid-fault. Worth one
  manual look at a station in FAULT state before calling Task 5 visually
  done.
- `render.yaml`'s `ALLOWED_ORIGIN` env var is `sync: false` (Render
  prompts for it, not stored here) -- confirm it's actually set to the
  real deployed frontend URL before relying on a production deploy; it
  was never exercised in this local-only session.
- `data/models/risk_v1` is deliberately committed, not gitignored (checked
  directly: `.gitignore` excludes `backend/data/models/*` generally but
  carves out `!backend/data/models/risk_v1/`), so Task 3's retrain landing
  byte-identical to what was already committed is exactly why the merge
  diff shows zero changes to it -- nothing to double-check there, this
  bullet is here only because an earlier draft of this section guessed
  wrong about its gitignore status before checking.

### Two still-open items, flagged so they don't get lost

Both trace back to the same original pre-overnight ask ("fix car-click
raycasting + look at scan cost"). The raycasting half was resolved as a
side effect of Task 5's Mirror rebuild. The scan-cost half was never
fully closed -- Task 6 found and fixed *one* instance of it, and in
writing this section I read the actual code behind both remaining call
sites to check whether they're the same problem or two:

- **`engine.current_state()`'s per-tick scan** (`replay/engine.py:47`):
  calls `RunData.sensor_is_reporting` / `machine_is_maintained` /
  `car_at_station_at` / `buffer_depth_at` / `latest_readings_at` once per
  station, every tick. All five of those methods were the exact ones
  Task 6 rewrote to use the new `_telemetry_by_station`/`_events_by_station`
  pre-grouped dicts -- so this path already benefits from that fix. Its
  remaining cost (Task 6 measured ~0.6-0.9s still going into a Floor
  Supervisor request after the fix, down from ~2.9s) is most likely each
  accessor still filtering *within* its now-smaller per-station slice by
  "timestamp <= now" from scratch on every call -- an O(rows-so-far) cost
  that grows as a run progresses, not yet indexed by time the way it's
  now indexed by station.
- **`predict/risk.py`'s `build_features`** (line 105): a completely
  different function, operating on `GenealogyStore` (built once at
  'load' time) via `_history_for_station`/`_shift_changes_for_station`,
  not on `RunData` at all. Task 6's fix never touched this path -- it
  wasn't even in the same module.

**Verdict: mechanically two problems, not one**, despite sharing a
family resemblance (both are "re-scan a growing history on every call").
They live in different modules, read different data structures, and
Task 6's fix demonstrably helped one and could not have touched the
other. That said, this is a code-reading conclusion, not a fresh
profiling run -- nobody has re-measured `current_state()`'s or
`build_features`'s actual cost against a real run since Task 6's fix
landed, so treat "not yet indexed by time" as a hypothesis worth
confirming with a profiler before spending effort on a fix, not a
confirmed root cause the way Task 6's own finding was.
