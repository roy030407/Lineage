# 🏭 Lineage

**A live digital twin of a vehicle assembly line**: synthetic sensor data streams in real time, and a chain of Predict → Trace → Act modules turns that stream into risk scores, root-cause traces, and bounded, auditable correction proposals.

![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/frontend-React%20%2B%20Three.js-149ECA?logo=react&logoColor=white)
![Tests](https://img.shields.io/badge/backend%20tests-137%20passing-brightgreen)
![Lint](https://img.shields.io/badge/ruff-clean-brightgreen)

> Nothing here hardcodes a station count, a layout shape, or a sensor mix. Every station, every conveyor segment, every lamp on screen is drawn straight from a `LineSpec`. Swap in a differently-shaped line and the whole system just follows.

## 🔍 What it actually does

Load a run, and 42 stations start ticking in real time in the browser: cars moving down the line, health lamps flipping color, buffers filling. Seed a defect at one station and it surfaces dozens of stations later at inspection, exactly the way a real plant hides problems until they're expensive. Then:

- **Predict** scores every car against a trained model and keeps score of its own alarms (precision, recall, false-alarm rate, a trust score) against what the run's own inspection data says actually happened.
- **Trace** takes a flagged car and ranks every upstream station by how much its readings deviated, naming the most likely origin and the cohort of other cars quietly exposed to the same thing.
- **Act** turns that into one bounded, envelope-checked proposal (never a rewrite of the line, a nudge back toward baseline) with a forked, non-destructive simulation of what it should do, and an immutable audit trail once someone approves it.

Run `scripts/demo.py` and it narrates all of this against a real seeded scenario, printing real numbers pulled live from the running system; nothing in the demo is scripted output.

## 🗺️ Architecture at a glance

```mermaid
flowchart LR
    subgraph Definition
        LS["LineSpec\nconfig/"]
    end
    subgraph Simulation
        DG["Datagen\ntelemetry · events\ninspection · ground truth"]
    end
    subgraph "Live twin"
        TW["Twin\nCarTwin · GenealogyStore"]
        RP["Replay\nWebSocket, tick by tick"]
    end
    subgraph Intelligence
        PR["Predict\nSPC · risk model · ledger"]
        TR["Trace\nroot-cause ranking"]
        AC["Act\nbounded proposals + audit"]
    end
    API["FastAPI"]
    FE["React + react-three-fiber\nMirror · role views · builder"]

    LS --> DG --> TW --> RP --> API
    TW --> PR --> TR --> AC --> API
    LS --> API
    API <-->|REST + WebSocket| FE
```

| Layer | What it does |
|---|---|
| `backend/lineage/config/` | `LineSpec`/`StationSpec`/etc., the plant definition everything else reads |
| `backend/lineage/datagen/` | Generates a run's `telemetry.csv`/`events.csv`/`inspection.csv`/`ground_truth.json` from a `LineSpec` + `RunConfig`, with seeded defect scenarios |
| `backend/lineage/twin/` | `CarTwin`/`GenealogyStore`, the object history a run's data gets ingested into |
| `backend/lineage/replay/` | Streams a loaded run's live state over a WebSocket, tick by tick |
| `backend/lineage/predict/` | SPC, a trained risk model, and a prediction ledger tracking whether each alarm materialized |
| `backend/lineage/trace/` | Root-cause tracing: given a flagged car, ranks upstream stations by deviation strength |
| `backend/lineage/act/` | Turns a trace result into a bounded, envelope-checked proposal with an immutable audit trail |
| `backend/lineage/api/` | FastAPI app exposing all of the above |
| `frontend/` | React + react-three-fiber Mirror scene, role views, and a station builder |

## 🚀 Setup

```
make install
```

Installs the backend (editable, with dev extras) and the frontend's npm dependencies.

## ▶️ Running

```
make dev-backend    # FastAPI on :8000
make dev-frontend   # Vite dev server on :5173
```

or `make dev` to run both together. Open the frontend URL, then use the "Load a run..." selector in the top bar (see **Generating data** below if none are listed).

## 🏗️ Generating data

```
make gen
```

Builds `default_400_car_run`: 400 cars over the bundled 42-station example line, with three named seeded scenarios (a torque drift, a paint-booth environmental excursion, an unflagged operator-handover shift), plus a low-rate background of unrelated material-quality noise. Deterministic: same seed, same output, every time.

Training a risk model (needed for the Prediction Ledger; the trained model itself is gitignored, so this is a one-time local step) is a separate script:

```
backend/.venv/Scripts/python.exe scripts/train_risk_model.py
```

## 🎬 Demo

```
backend/.venv/Scripts/python.exe scripts/demo.py       # Windows
backend/.venv/bin/python scripts/demo.py               # macOS/Linux
```

A six-beat narrated walkthrough, built entirely around the real seeded torque-drift scenario in `default_400_car_run`; every id, timestamp, and number it prints is read from that run or fetched live from the running API, never hardcoded:

1. **Mirror**: loads the run live, the browser starts ticking.
2. **Predict & the Ledger**: real precision/recall/trust-score for the station that actually caught the drift.
3. **Trace**: root-causes a flagged car back through the line and names the exposed cohort.
4. **Act**: generates, simulates, and approves a bounded correction, audit trail included.
5. **Leadership**: a real `GET /api/view/leadership` call, proving the response has no per-station data at all.
6. **Builder**: a real mid-line station insert, proving the station count and sequencing actually change.

Assumes the backend is already running and the frontend is open in a browser; it drives the API and prints narration for a live presenter, pausing for Enter between beats. Pass `--auto` to run unattended instead (a quick preview, or a smoke test).

Beats 3 and 4 (Trace and Act) call their functions directly in Python, not through the API; see **Known limitations** below.

## ✅ Testing and linting

```
make test    # backend: pytest -q
make lint    # backend: ruff check .
```

Frontend: `cd frontend && npx tsc --noEmit && npx vitest run`.

## 📝 Stated assumptions and scope decisions

A running list of judgment calls made while building this, kept honest rather than silently baked in:

- **Role views** (`GET /api/view/{role}`) reshape and filter the *existing* live line state per role. They do not yet incorporate Predict's bottleneck/risk analytics. Operator sees exactly one station; Leadership sees only summary counters, enforced by the response model itself, not by the frontend choosing not to render fields.
- **The station builder** covers insert/remove/reorder/save. Drag-and-drop reordering (buttons instead), a dedicated sensor-editor screen (an inline repeater instead), a commissioning wizard with "run to learn", and a visual 2D layout editor (plain numeric x/y fields instead) were cut as separately-scoped, bigger follow-ups.
- **Prediction Ledger `trust_score`** is defined as F1 (the harmonic mean of precision and recall). That is a standard, defensible single-number summary, not a domain-specific formula. There is no one fixed definition of "trust score"; this is a named judgment call, not an implicit one.
- **A station with no sensor, or a prediction below its coverage threshold, is `UNKNOWN_RISK`**: never a numeric level and never treated as safe. Any metric with a zero denominator (e.g. precision with no alarms raised at all) is `None`, never a fabricated `0.0`.
- **Act proposals never leave the safety envelope** in `backend/lineage/act/envelope.py`; `simulate()` runs on a deep-copied fork of the `LineSpec` and never writes to the live line.
- **Trace and Act have no API endpoints or frontend UI yet.** Both modules are implemented and tested; `scripts/demo.py` calls them directly in Python to show real output, narrated explicitly as "no UI yet" rather than pretending otherwise.

## ⚠️ Known limitations

- **Car clicks don't register in the Mirror scene.** Confirmed via a dense on-screen grid of clicks against a car known to be rendered there, and via instrumented click/hover logging: the ray always resolves to the station behind/below it instead. Station clicks work correctly through the same event system, so this looks like an InstancedMesh-specific raycasting issue, not a general one. Unfixed; needs its own investigation, likely a move off `InstancedMesh` for cars.
- **`RunData` and `assess_risk`'s feature builder scan more of a run's data as simulated time advances**, rather than using an index. Measured costs: `current_state()` went from near-instant to 4-8s over a single loaded run (mitigated in the role-view/Mirror endpoints by reusing the last broadcast snapshot instead of recomputing); building the full prediction ledger for a 400-car run measured ~105s (mitigated by building it lazily on first request instead of at 'load' time, then caching it). The underlying scan-cost pattern itself is unfixed: a real refactor candidate (pre-sorted/indexed lookups, matching how `GenealogyStore` already uses `bisect`), flagged rather than attempted here.
