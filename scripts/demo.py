"""Five-minute narrated walkthrough of Lineage, built entirely around the
real seeded torque_drift defect already present in default_400_car_run's
ground truth -- every station id, car id, and timestamp printed below is
read from that run, never hardcoded, so the narration stays accurate even
if the scenario itself changes.

Assumes the backend is already running (`make dev-backend`) and the
frontend is open in a browser (`make dev-frontend`); this script drives the
API and prints narration for a live presenter, it does not start either
server itself. Run with the backend's own venv python (same requirement as
scripts/gen_example_42.py and scripts/train_risk_model.py), from the repo
root:

    backend/.venv/Scripts/python.exe scripts/demo.py     (Windows)
    backend/.venv/bin/python scripts/demo.py             (macOS/Linux)

Pass --auto to run unattended (a quick preview, or a CI smoke test) instead
of pausing for Enter between acts -- deliberately explicit rather than
inferred from whether stdin looks like a terminal: that turned out not to
be a reliable signal across terminal/OS combinations in practice (input()
raised EOFError immediately the first time stdin wasn't a real tty, but not
consistently on every call after that), so --auto is a plain, unambiguous
switch instead of another guess.
"""

import json
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from lineage.act.ledger import AuditLedger, approve  # noqa: E402
from lineage.act.models import ApproverRole  # noqa: E402
from lineage.act.proposals import propose, simulate  # noqa: E402
from lineage.config.specs import LineSpec  # noqa: E402
from lineage.datagen.models import RunConfig  # noqa: E402
from lineage.trace.lineage_query import trace  # noqa: E402
from lineage.twin.ingest import from_generated_run  # noqa: E402

RUN_ID = "default_400_car_run"
RUN_DIR = BACKEND_DIR / "data" / "runs" / RUN_ID
LINE_PATH = BACKEND_DIR / "data" / "lines" / "example_42.yaml"
API_BASE = "http://localhost:8000"

# 'load' alone can take ~20s for a 400-car run (genealogy_store construction),
# and a cold prediction-ledger build measured ~105s -- httpx's 5s default
# would time out on both. The one deliberately short-timeout call is the
# up-front reachability check in check_prerequisites, which wants to fail
# fast if the backend simply isn't running at all.
client = httpx.Client(timeout=120.0)
AUTO_MODE = "--auto" in sys.argv[1:]


def pause() -> None:
    if AUTO_MODE:
        print("\n[--auto: pausing 2s instead of waiting for Enter]")
        time.sleep(2)
        return
    try:
        input("\n[Press Enter to continue] ")
    except EOFError:
        # --auto is the deliberate, explicit way to skip pauses; this is just
        # a safety net for someone forgetting it in a non-interactive context
        # (stdin closed/redirected), so the script degrades instead of
        # crashing on an unhandled EOFError.
        print("(stdin closed -- pausing 2s instead)")
        time.sleep(2)


def banner(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def check_prerequisites() -> None:
    if not RUN_DIR.exists():
        print(f"No run found at {RUN_DIR}.")
        print("Generate it first, from the repo root:  make gen")
        sys.exit(1)
    try:
        httpx.get(f"{API_BASE}/api/line", timeout=10.0).raise_for_status()
    except httpx.HTTPError:
        print(f"Backend not reachable at {API_BASE}.")
        print("Start it first, from the repo root:  make dev-backend")
        sys.exit(1)


def find_torque_drift_scenario() -> tuple[dict, str]:
    """Returns the ground-truth defect record plus the specific car whose
    inspection.csv row actually matches its recorded detection -- not just
    any car in cars_exposed, the one genuinely responsible for the catch."""
    ground_truth = json.loads((RUN_DIR / "ground_truth.json").read_text())
    defect = next(
        (d for d in ground_truth["defects"] if d["mechanism"] == "torque_drift"), None
    )
    if defect is None:
        print("No torque_drift defect in this run's ground truth -- was it")
        print("generated with a different scenario set? Try: make gen")
        sys.exit(1)

    inspection = pd.read_csv(RUN_DIR / "inspection.csv", parse_dates=["timestamp"])
    match = inspection[
        (inspection.station_id == defect["detected_at_station_id"])
        & (inspection.car_id.isin(defect["cars_exposed"]))
        & (inspection.result == "fail")
    ]
    flagged_car = match.iloc[0].car_id if not match.empty else defect["cars_exposed"][0]
    return defect, flagged_car


def main() -> None:
    check_prerequisites()
    defect, flagged_car = find_torque_drift_scenario()
    origin_station = defect["origin_station_id"]
    detected_station = defect["detected_at_station_id"]
    exposed_cars = defect["cars_exposed"]

    banner("LINEAGE -- live digital twin of a vehicle assembly line")
    print(f"Demo run: {RUN_ID}")
    print(
        f"Real seeded scenario: a torque_drift defect began at {origin_station} "
        f"at {defect['onset_timestamp']}, undetected until {detected_station} -- "
        f"{len(exposed_cars)} cars exposed before inspection caught it, "
        f"first at {flagged_car}."
    )
    pause()

    banner("ACT 1 -- MIRROR: the live twin")
    client.post(
        f"{API_BASE}/api/replay/control", json={"action": "load", "run_id": RUN_ID}
    ).raise_for_status()
    client.post(
        f"{API_BASE}/api/replay/control",
        json={"action": "set_speed", "speed_multiplier": 60},
    ).raise_for_status()
    client.post(f"{API_BASE}/api/replay/control", json={"action": "play"}).raise_for_status()
    print("Run loaded and playing at 60x -- switch to the browser now.")
    print("Every station, conveyor segment, and car on screen is drawn straight")
    print("from this line's LineSpec. Nothing here hardcodes a station count")
    print("or a layout shape; a differently-shaped line would just look different.")
    pause()

    banner("ACT 2 -- PREDICT & THE PREDICTION LEDGER")
    print(
        f"This exact drift, seeded at {origin_station}, is invisible there -- "
        f"{detected_station} is the only place it actually gets caught, "
        "36 stations downstream."
    )
    try:
        response = client.get(
            f"{API_BASE}/api/predict/metrics",
            params={"station_id": detected_station},
        )
        response.raise_for_status()
        metrics = response.json()
        print(f"\nReal numbers for {detected_station}, from this run's own ledger:")
        print(f"  precision:         {metrics['precision']}")
        print(f"  recall:            {metrics['recall']}")
        print(f"  false alarm rate:  {metrics['false_alarm_rate']}")
        print(f"  trust score:       {metrics['trust_score']}")
    except httpx.HTTPStatusError:
        print(
            "\nNo prediction ledger available for this run -- data/models/ is "
            "gitignored, so a fresh clone or CI environment has no trained "
            "risk model yet. (Same message the UI itself shows, not hidden.)"
        )
    print("\nSwitch to the 'Prediction Ledger' role view in the browser now.")
    pause()

    banner("ACT 3 -- TRACE: root-causing it back")
    print("Trace has no UI yet -- this calls the exact same function a future")
    print(f"role view would, directly: tracing {flagged_car} back from {detected_station}.")
    print(
        f"Watch which station it names as the origin -- the seeded scenario planted "
        f"a drift at {origin_station}, but Trace scores EVERY upstream station's "
        "deviation for this specific car and ranks by strength, not by which one "
        "the scenario was written around. Real background variance can outscore "
        "the seeded signal for any individual car; that's a feature, not a bug."
    )
    line = LineSpec.from_yaml(LINE_PATH)
    run_config = RunConfig.model_validate_json((RUN_DIR / "run_config.json").read_text())
    store = from_generated_run(line, RUN_DIR, run_config)
    trace_result = trace(
        line=line, store=store, car_id=flagged_car, flagged_at_station_id=detected_station
    )

    print(
        f"\nOriginating station: {trace_result.originating_station_id} "
        f"(verifiable: {trace_result.originating_is_verifiable})"
    )
    if trace_result.originating_station_id != origin_station:
        print(
            f"(Differs from the seeded origin {origin_station}, which is still visible "
            "further down the ranked list below -- both deviations are real.)"
        )
    print("Ranked contributions:")
    for cause in trace_result.ranked_contributions[:5]:
        print(f"  {cause.station_id}: score={cause.contribution_score:.2f} z={cause.deviation_z}")
    print(f"\n{len(trace_result.affected_cars)} other cars found exposed under similar conditions:")
    for car in trace_result.affected_cars[:5]:
        print(f"  {car.car_id}: confidence={car.exposure_confidence:.2f}")
    pause()

    banner("ACT 4 -- ACT: a bounded, auditable proposal")
    print("Act has no UI yet either -- this is the same bounded-proposal engine")
    print("a floor supervisor's approval screen would call.")
    proposals = propose(trace_result, line)
    if not proposals:
        print(
            f"\nNo changeable parameters at {trace_result.originating_station_id} "
            "to propose against in this LineSpec."
        )
    else:
        proposal = proposals[0]
        print(f"\nProposal {proposal.proposal_id}:")
        print(
            f"  {proposal.station_id}.{proposal.parameter_name}: "
            f"{proposal.current_value} -> {proposal.proposed_value}"
        )
        print(f"  rationale: {proposal.rationale}")

        origin_cause = next(
            (
                c
                for c in trace_result.ranked_contributions
                if c.station_id == trace_result.originating_station_id
            ),
            None,
        )
        deviation_z = (origin_cause.deviation_z if origin_cause else None) or 0.0
        effect = simulate(proposal, line, current_deviation_z=deviation_z)
        print("\nForked-simulation prediction (never touches the live line):")
        print(
            f"  predicted defect-rate delta: {effect.predicted_defect_rate_delta:+.3f} "
            f"(95% CI {effect.defect_rate_confidence_interval})"
        )

        ledger = AuditLedger()
        record = approve(proposal, ApproverRole.FLOOR_SUPERVISOR, "demo-supervisor", ledger)
        print(
            f"\nApproved by {record.approver_role.value} ({record.approver_id}) "
            f"at {record.timestamp}. Immutable audit record written -- "
            f"{len(ledger.all_records())} record(s) in this session's ledger."
        )
    pause()

    banner("ACT 5 -- EVERYONE ELSE'S VIEW")
    print("Back in the browser: the role selector switches between Operator")
    print("(one station, nothing else), Floor Supervisor (the full line plus")
    print("active alerts), Plant Manager, and Leadership (summary counters")
    print("only -- no per-station detail in that response at all).")
    print("The 'Builder' toggle edits a LineSpec live: insert or remove a")
    print("station, reorder it, save the result as a new line file.")
    print("\nThat's Lineage.")


if __name__ == "__main__":
    main()
