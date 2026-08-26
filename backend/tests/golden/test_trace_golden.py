"""Golden test: Trace evaluated against the real default 400-car run must
name the correct originating station for the seeded torque-drift scenario,
and its affected-cohort list must recover the ground-truth exposed cars with
reported precision/recall -- not asserted as a perfect 1.0, since this is a
real detector being graded against a real answer key."""

import json

import pytest

from lineage.config.loader import load_line_spec
from lineage.datagen.cli import DEFAULT_LINE_PATH, build_default_run_config
from lineage.datagen.run import generate_run
from lineage.trace.lineage_query import trace
from lineage.twin.ingest import from_generated_run


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)
    output_root = tmp_path_factory.mktemp("trace_golden_run")
    artifacts = generate_run(line, config, output_root=output_root)
    store = from_generated_run(line, artifacts.output_dir, config)
    ground_truth = json.loads(artifacts.ground_truth_path.read_text())
    return line, store, ground_truth


def test_trace_names_torque_drift_origin_and_recovers_exposed_cohort(default_run):
    line, store, ground_truth = default_run

    defect = next(d for d in ground_truth["defects"] if d["mechanism"] == "torque_drift")
    assert defect["origin_station_id"] == "ST-06"
    truth_exposed = set(defect["cars_exposed"])

    flagged_car_id = defect["cars_exposed"][len(defect["cars_exposed"]) // 2]

    result = trace(
        line=line,
        store=store,
        car_id=flagged_car_id,
        flagged_at_station_id=defect["detected_at_station_id"],
    )

    assert result.originating_station_id == "ST-06"

    predicted_exposed = {c.car_id for c in result.affected_cars}
    true_positives = predicted_exposed & truth_exposed
    precision = len(true_positives) / len(predicted_exposed) if predicted_exposed else 0.0
    recall = len(true_positives) / len(truth_exposed) if truth_exposed else 0.0

    print(
        f"\naffected-cohort precision={precision:.3f} recall={recall:.3f} "
        f"(predicted={len(predicted_exposed)}, truth={len(truth_exposed)}, "
        f"true_positives={len(true_positives)})"
    )

    assert precision > 0.5
    assert recall > 0.5
