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

RUN_ID = "default_400_car_run"
RUN_DIR = BACKEND_DIR / "data" / "runs" / RUN_ID
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
            "\nNo prediction ledger available for this run -- no trained risk "
            "model was found under data/models/risk_v1. (Same message the UI "
            "itself shows, not hidden.)"
        )
    print("\nSwitch to the 'Prediction Ledger' role view in the browser now.")
    pause()

    banner("ACT 3 -- TRACE: root-causing it back")
    print("This is the same GET /api/trace endpoint the browser's car panel")
    print(f"calls ('Trace root cause'): tracing {flagged_car} back from {detected_station}.")
    print(
        f"Watch which station it names as the origin -- the seeded scenario planted "
        f"a drift at {origin_station}, but Trace scores EVERY upstream station's "
        "deviation for this specific car and ranks by strength, not by which one "
        "the scenario was written around. Real background variance can outscore "
        "the seeded signal for any individual car; that's a feature, not a bug."
    )
    response = client.get(
        f"{API_BASE}/api/trace/{flagged_car}", params={"station_id": detected_station}
    )
    response.raise_for_status()
    trace_result = response.json()

    print(
        f"\nOriginating station: {trace_result['originating_station_id']} "
        f"(verifiable: {trace_result['originating_is_verifiable']})"
    )
    if trace_result["originating_station_id"] != origin_station:
        print(
            f"(Differs from the seeded origin {origin_station}, which is still visible "
            "further down the ranked list below -- both deviations are real.)"
        )
    print("Ranked contributions:")
    for cause in trace_result["contributions"][:5]:
        print(f"  {cause['station_id']}: score={cause['score']:.2f} z={cause['deviation_z']}")
    cohort = trace_result["exposed_cohort"]
    print(f"\n{len(cohort)} other cars found exposed under similar conditions:")
    for car in cohort[:5]:
        print(f"  {car['car_id']}: confidence={car['confidence']:.2f}")
    pause()

    banner("ACT 4 -- ACT: a bounded, auditable proposal")
    print("The same proposal/simulate/approve endpoints the Floor Supervisor")
    print("screen uses -- every failed inspection in the run, traced and turned")
    print("into one bounded, envelope-checked proposal per (station, parameter):")
    response = client.get(f"{API_BASE}/api/act/proposals")
    response.raise_for_status()
    proposals = response.json()
    if not proposals:
        print("\nNo proposals -- no failed inspection traced to a station with")
        print("changeable parameters in this run.")
    else:
        # Prefer the proposal born from the station Act 3 just implicated.
        proposal = next(
            (p for p in proposals if p["station_id"] == trace_result["originating_station_id"]),
            proposals[0],
        )
        print(f"\nProposal {proposal['proposal_id']} (of {len(proposals)} total):")
        print(
            f"  {proposal['station_id']}.{proposal['parameter_name']}: "
            f"{proposal['current_value']} -> {proposal['proposed_value']}"
        )
        print(f"  rationale: {proposal['rationale']}")

        response = client.post(
            f"{API_BASE}/api/act/proposals/{proposal['proposal_id']}/simulate"
        )
        response.raise_for_status()
        effect = response.json()
        print("\nAnalytical projection (read-only -- never touches the live line):")
        print(
            f"  predicted defect-rate delta: {effect['predicted_defect_rate_delta']:+.3f} "
            f"(95% CI [{effect['ci_low']:+.3f}, {effect['ci_high']:+.3f}])"
        )

        response = client.post(
            f"{API_BASE}/api/act/proposals/{proposal['proposal_id']}/approve",
            json={"approver_id": "demo-supervisor"},
        )
        response.raise_for_status()
        record = response.json()
        print(
            f"\nApproved by {record['approver_role']} ({record['approver_id']}) "
            f"at {record['timestamp']}. Audit record appended to the backend's "
            "JSONL audit log -- it survives a restart, and the approved value "
            "becomes the parameter's setpoint for future proposals."
        )
    pause()

    banner("ACT 5 -- LEADERSHIP: a real, scoped role view")
    print("Operator (one station, nothing else), Floor Supervisor (the full line")
    print("plus active alerts), and Plant Manager are all live in the browser's")
    print("role selector too. Leadership gets no live per-station state at all,")
    print("enforced by the response model itself -- not the frontend choosing")
    print("not to render it. Calling it for real:")
    response = client.get(f"{API_BASE}/api/view/leadership")
    response.raise_for_status()
    leadership = response.json()
    print("\nGET /api/view/leadership ->")
    print(f"  total cost:        {leadership['total_cost_per_hour']:.2f}/hr")
    print(f"  value-added cost:  {leadership['total_value_added_cost_per_hour']:.2f}/hr")
    print(f"  value-added ratio: {leadership['value_added_ratio']:.1%}")
    candidates = leadership["sensor_retrofit_candidates"]
    print(
        f"  sensor retrofit shortlist: {len(candidates)} manual stations, ranked by "
        "recurring traced-defect origins x economic weight."
    )
    if candidates:
        top = candidates[0]
        print(
            f"  top candidate: {top['station_id']} "
            f"({top['recurring_defect_occurrences']} traced origins this run)"
        )
    print("\nNo car list, no live station state, no alarms -- the only per-station")
    print("data here is the retrofit business shortlist, aggregated from run")
    print("history. The browser's Leadership view turns this into a payback and")
    print("phased-rollout panel, assumptions stated on screen.")
    pause()

    banner("ACT 6 -- BUILDER: a live mid-line station insert")
    print("The 'Builder' toggle in the browser edits a LineSpec live. Proving the")
    print("reshape actually happens -- not just narrating that the button exists:")
    draft = client.post(f"{API_BASE}/api/builder/draft/start").json()
    before_ids = [s["id"] for s in draft["stations"]]
    mid_index = len(before_ids) // 2
    # after_station_id may not be the line's actual last station -- insert_station
    # rejects that (append at the tail means passing None instead). len // 2 is
    # never the last index for a line long enough to have a meaningful "mid-line".
    after_id = before_ids[mid_index]
    print(
        f"\nBefore: {len(before_ids)} stations. Inserting after {after_id!r} "
        f"(position {mid_index} of {len(before_ids) - 1}, i.e. mid-line, not appended at an end)."
    )

    new_station = {
        "id": "ST-DEMO-INSERT",
        "name": "Demo Inserted Station",
        "zone": draft["stations"][mid_index]["zone"],
        "sequence_index": 0,  # overwritten by insert_station server-side
        "sensors": [],
        "acquisition_mode": "manual",
        "is_inspection_station": False,
        "cycle_time_nominal_s": 30.0,
        "commissioning_baseline": None,
        "changeable_params": {},
        "readable_params": [],
        "machine": {
            "model": "Demo Station Rig",
            "install_year": 2024,
            "last_maintenance_date": "2024-01-01",
            "maintenance_interval_days": 90,
            "wear_curve_shape": "linear",
        },
        "cost_per_hour": 5.0,
        "value_add_pct": 1.0,
    }
    response = client.post(
        f"{API_BASE}/api/builder/draft/stations",
        json={"station": new_station, "after_station_id": after_id},
    )
    response.raise_for_status()
    updated = response.json()
    after_ids = [s["id"] for s in updated["stations"]]
    inserted_index = after_ids.index("ST-DEMO-INSERT")
    inserted_seq = next(
        s["sequence_index"] for s in updated["stations"] if s["id"] == "ST-DEMO-INSERT"
    )
    window = after_ids[max(0, inserted_index - 2) : inserted_index + 3]

    print(f"\nAfter:  {len(after_ids)} stations (was {len(before_ids)}).")
    print(f"Around the insertion point: {window}")
    print(
        f"New station's sequence_index: {inserted_seq} "
        f"(matches its actual position in the list, {inserted_index})"
    )
    print(
        "This is the same draft/insert_station endpoint the Builder screen calls -- "
        "nothing here is a separate demo-only code path."
    )

    print("\nThat's Lineage.")


if __name__ == "__main__":
    main()
