# Lineage

A live digital twin of a vehicle assembly line: a synthetic plant generates
realistic sensor data, a replay engine streams it as if it were happening
now, and a set of Predict/Trace/Act modules turn that stream into risk
scores, root-cause traces, and bounded, auditable correction proposals.
Nothing in the system hardcodes a station count, a layout shape, or a
sensor mix -- everything is read from a `LineSpec`, so a differently-shaped
line just works.

## Architecture at a glance

| Layer | What it does |
|---|---|
| `backend/lineage/config/` | `LineSpec`/`StationSpec`/etc. -- the plant definition everything else reads |
| `backend/lineage/datagen/` | Generates a run's `telemetry.csv`/`events.csv`/`inspection.csv`/`ground_truth.json` from a `LineSpec` + `RunConfig`, with seeded defect scenarios |
| `backend/lineage/twin/` | `CarTwin`/`GenealogyStore` -- the object history a run's data gets ingested into |
| `backend/lineage/replay/` | Streams a loaded run's live state over a WebSocket, tick by tick |
| `backend/lineage/predict/` | SPC, a trained risk model, and a prediction ledger tracking whether each alarm materialized |
| `backend/lineage/trace/` | Root-cause tracing: given a flagged car, ranks upstream stations by deviation strength |
| `backend/lineage/act/` | Turns a trace result into a bounded, envelope-checked proposal with an immutable audit trail |
| `backend/lineage/api/` | FastAPI app exposing all of the above |
| `frontend/` | React + react-three-fiber Mirror scene, role views, and a station builder |

## Setup

```
make install
```

Installs the backend (editable, with dev extras) and the frontend's npm
dependencies.

## Running

```
make dev-backend    # FastAPI on :8000
make dev-frontend   # Vite dev server on :5173
```

or `make dev` to run both together. Open the frontend URL, then use the
"Load a run..." selector in the top bar (see **Generating data** below if
none are listed).

## Generating data

```
make gen
```

Builds `default_400_car_run`: 400 cars over the bundled 42-station example
line, with three named seeded scenarios (a torque drift, a paint-booth
environmental excursion, an unflagged operator-handover shift), plus a
low-rate background of unrelated material-quality noise. Deterministic --
same seed, same output, every time.

Training a risk model (needed for the Prediction Ledger; the trained model
itself is gitignored, so this is a one-time local step) is a separate
script:

```
backend/.venv/Scripts/python.exe scripts/train_risk_model.py
```

## Demo

```
backend/.venv/Scripts/python.exe scripts/demo.py       # Windows
backend/.venv/bin/python scripts/demo.py               # macOS/Linux
```

A five-act narrated walkthrough, built entirely around the real seeded
torque-drift scenario in `default_400_car_run` (every id and timestamp it
prints is read from that run's own ground truth, not hardcoded). Assumes
the backend is already running and the frontend is open in a browser --
it drives the API and prints narration for a live presenter, pausing for
Enter between acts. Pass `--auto` to run unattended instead (a quick
preview, or a smoke test).

Acts 3 and 4 (Trace and Act) call their functions directly in Python, not
through the API -- see **Known limitations** below.

## Testing and linting

```
make test    # backend: pytest -q
make lint    # backend: ruff check .
```

Frontend: `cd frontend && npx tsc --noEmit && npx vitest run`.

## Stated assumptions and scope decisions

A running list of judgment calls made while building this, kept honest
rather than silently baked in:

- **Role views** (`GET /api/view/{role}`) reshape and filter the *existing*
  live line state per role -- they do not yet incorporate Predict's
  bottleneck/risk analytics. Operator sees exactly one station; Leadership
  sees only summary counters, enforced by the response model itself, not
  by the frontend choosing not to render fields.
- **The station builder** covers insert/remove/reorder/save. Drag-and-drop
  reordering (buttons instead), a dedicated sensor-editor screen (an inline
  repeater instead), a commissioning wizard with "run to learn", and a
  visual 2D layout editor (plain numeric x/y fields instead) were cut as
  separately-scoped, bigger follow-ups.
- **Prediction Ledger `trust_score`** is defined as F1 (the harmonic mean
  of precision and recall) -- a standard, defensible single-number summary,
  not a domain-specific formula. There is no one fixed definition of "trust
  score"; this is a named judgment call, not an implicit one.
- **A station with no sensor, or a prediction below its coverage
  threshold, is UNKNOWN_RISK** -- never a numeric level and never treated
  as safe. Any metric with a zero denominator (e.g. precision with no
  alarms raised at all) is `None`, never a fabricated `0.0`.
- **Act proposals never leave the safety envelope** in
  `backend/lineage/act/envelope.py`; `simulate()` runs on a deep-copied
  fork of the `LineSpec` and never writes to the live line.
- **Trace and Act have no API endpoints or frontend UI yet.** Both modules
  are implemented and tested; `scripts/demo.py` calls them directly in
  Python to show real output, narrated explicitly as "no UI yet" rather
  than pretending otherwise.

## Known limitations

- **Car clicks don't register in the Mirror scene.** Confirmed via a dense
  on-screen grid of clicks against a car known to be rendered there, and
  via instrumented click/hover logging: the ray always resolves to the
  station behind/below it instead. Station clicks work correctly through
  the same event system, so this looks like an InstancedMesh-specific
  raycasting issue, not a general one. Unfixed; needs its own
  investigation, likely a move off `InstancedMesh` for cars.
- **`RunData` and `assess_risk`'s feature builder scan more of a run's data
  as simulated time advances**, rather than using an index. Measured costs:
  `current_state()` went from near-instant to 4-8s over a single loaded
  run (mitigated in the role-view/Mirror endpoints by reusing the last
  broadcast snapshot instead of recomputing); building the full prediction
  ledger for a 400-car run measured ~105s (mitigated by building it lazily
  on first request instead of at 'load' time, then caching it). The
  underlying scan-cost pattern itself is unfixed -- a real refactor
  candidate (pre-sorted/indexed lookups, matching how `GenealogyStore`
  already uses `bisect`), flagged rather than attempted here.
