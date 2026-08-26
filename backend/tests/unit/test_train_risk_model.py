"""Tests for scripts/train_risk_model.py's pure helper functions (split
ordering, metrics reporting) -- not a full re-run of the training pipeline,
which is already exercised manually and takes much longer."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from train_risk_model import randomized_run_config, report, time_split  # noqa: E402

from lineage.config.loader import load_line_spec  # noqa: E402
from lineage.datagen.cli import DEFAULT_LINE_PATH  # noqa: E402


def test_time_split_never_reorders_and_respects_fractions():
    base = datetime(2024, 1, 1)
    samples = [{"entry_time": base + timedelta(seconds=i)} for i in range(100)]

    train, calibrate, test = time_split(samples)

    assert len(train) == 60
    assert len(calibrate) == 20
    assert len(test) == 20
    assert max(s["entry_time"] for s in train) <= min(s["entry_time"] for s in calibrate)
    assert max(s["entry_time"] for s in calibrate) <= min(s["entry_time"] for s in test)


def test_report_computes_expected_metric_keys():
    y_true = [0, 0, 1, 1]
    y_pred_proba = [0.1, 0.4, 0.6, 0.9]

    metrics = report("test-model", y_true, y_pred_proba)

    assert set(metrics.keys()) == {"precision", "recall", "f1", "auc"}
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0


def test_randomized_run_config_places_scenarios_independently_per_seed():
    line = load_line_spec(DEFAULT_LINE_PATH)

    config_a = randomized_run_config(line, "test-a", seed=1)
    config_b = randomized_run_config(line, "test-b", seed=2)

    onset_a = config_a.defect_seeds[0].onset_car_index
    onset_b = config_b.defect_seeds[0].onset_car_index
    assert onset_a != onset_b  # different seeds land at different windows

    # Every scenario window must fit inside the run and leave room for its
    # own duration, regardless of seed.
    for config in (config_a, config_b):
        seed = config.defect_seeds[0]
        assert 0 <= seed.onset_car_index <= config.num_cars - seed.duration_cars
        excursion = config.environment_excursions[0]
        assert 0 <= excursion.start_car_index < excursion.end_car_index < config.num_cars
