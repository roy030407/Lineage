# Lineage — Design Reference

This is the durable reference for the UI overhaul (`feat/ui-overhaul`). It
replaces the design plan approved in conversation during Prompt A, which was
never written down and got lost to context compaction partway through the
overnight package — a mistake this file exists to make impossible to repeat.
From here on, later tasks cite "per DESIGN.md," not "per the approved plan."

The palette, type scale, and status vocabulary below are already implemented
in `frontend/src/styles/tokens.ts` (Task 4) — this file documents them for
reference and reasoning; `tokens.ts` is still the actual source of truth for
the values themselves. The Mirror/Builder wireframes, node anatomy, and
signature element are the parts that existed only in conversation and are
being reconstructed fresh here (Task 5), reasoned from what's already built
rather than invented from nothing.

## Palette

An industrial, low-saturation base with three high-saturation "beacon" accent
colors reserved *only* for status signals — never used decoratively, so a
colored object on screen always means something.

| Token | Hex | Use |
|---|---|---|
| `foundry` | `#22231f` | Base canvas (background) |
| `castSteel` | `#4a4e47` | Panels, dividers, structural chrome, conveyor track |
| `vellum` | `#dad5c6` | Primary text, car bodies |
| `beaconGreen` | `#4c9a5b` | Status: healthy / good |
| `beaconAmber` | `#e8a33d` | Status: caution, selection highlight |
| `beaconRed` | `#c43b3b` | Status: fault |
| `steelNeutral` | `#7a8380` | Status: no signal (not a fault) |

## Type

| Role | Family | Used for |
|---|---|---|
| Display | Big Shoulders Condensed | Headers, station IDs, hero numbers — tall, condensed, stencil-adjacent, reads as industrial signage rather than a generic UI font |
| Body | IBM Plex Sans | Paragraph text, labels, form fields |
| Mono | IBM Plex Mono | Sensor readings, data tables, timestamps — tabular figures so columns of numbers align |

Scale (`TYPE_SCALE` in `tokens.ts`): `display` (2.5rem/700), `h1` (1.5rem/600),
`h2` (1.125rem/500), `body` (0.9375rem/400), `eyebrow` (0.75rem/600,
uppercase, letter-spaced), `data` (0.875rem/400 mono), `dataHero` (1.75rem/500
mono).

Spacing: an 8-step scale, `space1`…`space12`, one step = 0.25rem. Nothing
should hand-write a `rem`/`px` margin, padding, or gap outside `tokens.ts`.

## Status vocabulary

Four backend enums, each state mapped to `{ color, shape, label }`
(`SENSOR_HEALTH_TOKENS` / `MACHINE_HEALTH_TOKENS` / `SPC_STATE_TOKENS` /
`RISK_LEVEL_TOKENS` in `tokens.ts`). One 5-shape vocabulary is reused across
all four, so shape carries a single consistent meaning everywhere in the
app — colour is never the only signal, so status survives a projector or a
colour-blind viewer:

| Shape | Meaning |
|---|---|
| ● circle | Healthy / in control / low risk |
| ▲ triangle | Caution, needs attention |
| ◆ diamond | Fault |
| ⬡ hexagon | Pending — not a fault, just no data yet |
| ○ ring | Not applicable / unknown — no meaningful signal at all |

**The distinction this whole vocabulary exists to protect:** a sensor that
has *never reported* (`NOT_YET_REPORTING`, hexagon, steel-neutral — simulated
time hasn't reached that station yet) and a sensor that *was* reporting and
has gone stale (`RED`, diamond, beacon-red — a real fault) used to be
conflated into one RED state. That conflation is what made a stalled replay
engine look identical to 29 simultaneous sensor faults (see
`NOTES-OVERNIGHT.md`, Task 2). Every surface that shows sensor health —
the Mirror's lamps, the Operator/Floor Supervisor/Plant Manager views —
must keep these visually and textually distinct. `NOT_APPLICABLE` (no
sensor installed at all, ring shape) is a *third*, again-distinct case:
not a fault, not a pending report, just "there is nothing to read here."

| Vocabulary | States |
|---|---|
| Sensor health | GREEN (●), RED (◆), NOT_YET_REPORTING (⬡), NOT_APPLICABLE (○) |
| Machine health | GREEN (●), RED (◆) |
| SPC state | IN_CONTROL (●), OUT_OF_CONTROL (◆), UNKNOWN (○), ENVIRONMENT_INVALID (▲) |
| Risk level | LOW (●), MEDIUM (▲), HIGH (◆), UNKNOWN_RISK (○) |

SPC state and risk level aren't surfaced by any current view — no endpoint
returns them yet — so their tokens are defined and ready, not yet wired into
a real view. That's Task 6 (role views) and Task 7 (Leadership ROI)'s job.

## Signature element: the beacon mast

*Proposed fresh for Task 5 — this is new, not a recovered decision.*

Every station's status lamps move from sitting directly on the block roof to
the top of a thin vertical mast rising above it — the same andon-tower
language a real plant floor uses, and the same silhouette Factorio's alarm
poles and Satisfactory's beacon structures use for exactly the same reason:
readable from across the whole floor, not just up close.

When a station is in a fault state (sensor or machine health RED — a real,
existing state, never fabricated for the demo), the mast also emits a thin
vertical light beam rising further into the sky: a translucent, additive,
`beaconRed`-emissive cone, visible across the entire 150m serpentine line.
This is the "you can see trouble from across the factory floor" moment —
built entirely from existing tokens (no new colour) and cheap geometry (a
few dozen triangles, rendered only for stations actually in fault state).

This is deliberately *the* recognizable shot: judges see the Mirror first,
and a lit beacon beam is legible in a screenshot, a demo video, or a
30-second glance across the room in a way a colored dot on a box never is.

## Mirror layout

```
+----------------------------------------------------------------------------+
| [Plant Name]  [Role: Mirror v] [Builder] [Load run v] [Play][Pause][Step]  |
|                                    [Speed 1x 10x 60x]         [Timestamp]  |
+----------------------------------------------------------------------------+
|                                                                  |         |
|   BODY   ●--●--●--●--...                                        |         |
|                        \    (zone label floats above each row;  | STATION |
|   PAINT      ●--●--●--●--    beacon masts visible on every       |  PANEL  |
|                        /     station; faulted masts glow)        | (click) |
|   FINAL  ●--●--●--●--...                                         +---------+
|                                                                  | CAR     |
|   [hover a station -> floating tooltip: readings + status]      |  PANEL  |
|   [cars ride the conveyor as small vellum blocks, riding         | (click) |
|    visibly above the station block top]                          |         |
|                                                                  |         |
|  [Orbit: drag=rotate, wheel=zoom]   [Following CAR-00042 · Stop] |         |
+----------------------------------------------------------------------------+
```

- Zone identity comes from two layered signals, not one: the real serpentine
  geometry (Task 3 — each zone its own row, separated by a corridor turn)
  *and* a floating zone label (`BODY`/`PAINT`/`FINAL`, display font, vellum)
  above each row, so identity doesn't depend on reading individual station
  IDs.
- Hover a station → a `drei` `Html`-anchored tooltip: station name/ID, the
  same `StatusBadge` treatment used in the 2D views (Task 4) for sensor and
  machine health, and the latest readings.
- Click a station → the existing `StationPanel` (readings, baseline,
  acquisition mode).
- Click a car → the existing `CarPanel` (stations visited, readings, dwell
  time) — currently broken; see the raycasting diagnosis below.
- Clicking a car also engages follow mode (already wired); a small
  "Following CAR-XXXX · Stop" indicator becomes visible so the state is never
  invisible, with a way back to free orbit.

## Builder layout (Task 8 — node-graph canvas, as built)

The spawn tray sits bottom-right, not left as first sketched here — an
explicit override given while building Task 8. Everything else below
matches what actually shipped in `frontend/src/builder/graph/`.

```
+----------------------------------------------------------------------------+
| [Plant Name]                [Role: Builder v]        [Close Builder]       |
+------------------------------------------------------------------+---------+
| [Edit envelope]                                                  | SAVE &  |
|                                                                   | ACTIVATE|
|   BODY row:  [node]--[node]--[node]--...                         | panel   |
|                  |                                                +---------+
|   PAINT row: [node]--[node]--...            (selecting a node    | PROPS   |
|                  |                            opens a properties |(sensors,|
|   FINAL row: [node]--[node]--...              panel here instead |distance,|
|                                                of this save panel)|baseline)|
|  connectors = conveyor segments; click one to cut it              +---------+
|                                                        +--------------------+
|                                                        | SPAWN TRAY         |
|                                                        | [Body][Paint]      |
|                                                        | [Final][Manual var]|
|                                                        | (drag onto a link  |
|                                                        |  to insert, or an  |
|                                                        |  end to append)    |
+--------------------------------------------------------+--------------------+
```

The properties panel and the save panel share the same top-right corner
(only one is ever relevant at a time — no node selected vs. one selected)
and the properties panel is deliberately height-capped, not stretched to
the bottom, so it can never cover the spawn tray sitting in that same
bottom-right corner.

### Node anatomy

```
+---------------------------+
| ▌ Body · ST-17            |   <- left edge stripe = zone identity colour
| Paint Station 17           |      (Task 8's own token, ZONE_TOKENS --
| 2 sensors                  |      the Mirror's zone identity comes from
| instrumented                |      row position, not a hue, so the flat
| o------------------------o |      2D canvas needed one of its own)
+---------------------------+
```

A manual station's sensor line reuses `SENSOR_HEALTH_TOKENS.not_applicable`
(the ring glyph, "No Sensor") — that token's real, already-true meaning at
config time, not a live-health claim the Builder has no run to back up. An
instrumented/mixed station just states its sensor count as plain text
instead, for the same reason: no draft has live telemetry to honestly call
"Reporting".

## Car-click raycasting bug — diagnosis (Task 5)

Confirmed live (paused replay, precise screen-projected clicks, then a
hover-hit sweep across the car's own bounding box): the car `InstancedMesh`
received **zero** pointer events of any kind — not click, not hover — even
at points mathematically guaranteed to sit inside its geometry. This ruled
out an occlusion/z-order theory (a station "winning" a depth race) before it
ruled anything in.

Root cause, confirmed against `three`'s installed source
(`InstancedMesh.raycast`, `three/src/objects/InstancedMesh.js:154-171`):
before testing any instance, `raycast()` broad-phase-rejects using
`this.boundingSphere` — a bounding volume cached on the `InstancedMesh`
object itself, computed once, lazily, on the *first* raycast call, from
whatever instance transforms happened to exist at that moment. `Car3D`
updates every instance's transform every frame via `setMatrixAt` (cars
entering, moving, leaving), but nothing ever recomputed `boundingSphere`
afterward, so the cached sphere goes permanently stale relative to where
cars actually are — the broad-phase check rejects the ray before the
per-instance narrow-phase test ever runs, silently, for every subsequent
click.

This is a **distinct bug from the earlier-fixed occlusion issue**, not a
resurfacing of it. The earlier fix (`frustumCulled={false}`) addresses
`Object3D`'s *own* bounding-sphere check used for render-time frustum
culling. This is a *sibling* bug in the same family (a stale per-object
cached bounding volume that ignores per-instance updates) but lives in a
completely separate code path — `InstancedMesh.raycast()`'s own
`this.boundingSphere`, not `geometry.boundingSphere` and not the frustum
check. Confirmed empirically: adding `mesh.computeBoundingSphere()` once per
frame (alongside the existing `instanceMatrix.needsUpdate = true`) restores
both hover and click events immediately, verified via a real Playwright
click on the exact projected car position → `CarPanel` opens.
