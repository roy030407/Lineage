"""Offline training for the risk model. Runtime (lineage.predict.risk) only
ever loads what this script produces; it never trains.

Trains on 3 independently-seeded runs with randomized scenario car-index
windows, not just the single fixed default run: a single run's scenarios sit
in disjoint car-index ranges, so a time-based test split ends up dominated by
whichever scenario happens to land last (see the model-comparison writeup for
the full finding). Splitting each run by time individually, then pooling the
train/calibrate/test portions across runs, keeps the "never shuffle, no
future leakage within a run" property while giving all three scenario types
a real chance of appearing in the test set.

Usage: run with the backend venv's python, from anywhere:
    backend/.venv/Scripts/python.exe scripts/train_risk_model.py
"""

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from lineage.config.loader import load_line_spec
from lineage.config.specs import LineSpec, Zone
from lineage.datagen.cli import DEFAULT_LINE_PATH, _default_operator_setup
from lineage.datagen.models import (
    DefectMechanism,
    DefectSeed,
    EnvironmentExcursion,
    RunConfig,
    ShiftAssignment,
)
from lineage.datagen.run import generate_run
from lineage.predict.risk import (
    FEATURE_NAMES,
    RAW_FEATURE_NAMES,
    build_features,
    build_raw_features,
)
from lineage.twin.ingest import from_generated_run
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

MODEL_DIR = BACKEND_DIR / "data" / "models" / "risk_v1"
TRAIN_FRACTION = 0.6
CALIBRATE_FRACTION = 0.2
COVERAGE_THRESHOLD = 0.5

TRAINING_RUN_SEEDS = [20240915, 20241001, 20241102]
TORQUE_DRIFT_STATION = "ST-06"
OPERATOR_SCENARIO_STATION = "ST-02"


def randomized_run_config(line: LineSpec, run_id: str, seed: int) -> RunConfig:
    """Same three scenario types as the canonical default run, but each
    placed at an independently randomized car-index window per run -- so
    pooling several of these gives a test split that isn't dominated by
    whichever scenario happens to sit last in a single fixed run."""
    rng = random.Random(seed)
    num_cars = 400

    torque_onset = rng.randint(20, num_cars - 60)
    excursion_onset = rng.randint(20, num_cars - 40)
    handover_onset = rng.randint(20, num_cars - 60)

    operator_profiles, operator_shift_schedule = _default_operator_setup(line)
    # Re-anchor the designated scenario station's handover to the randomized
    # onset instead of the canonical default's fixed car 200.
    operator_shift_schedule = [
        a for a in operator_shift_schedule if a.station_id != OPERATOR_SCENARIO_STATION
    ]
    scenario_prefix = f"OP-{OPERATOR_SCENARIO_STATION}"
    op_a = next(p for p in operator_profiles if p.operator_id == f"{scenario_prefix}-A")
    op_b = next(p for p in operator_profiles if p.operator_id == f"{scenario_prefix}-B")

    operator_shift_schedule += [
        ShiftAssignment(
            station_id=OPERATOR_SCENARIO_STATION,
            operator_id=op_a.operator_id,
            start_car_index=0,
            end_car_index=handover_onset - 1,
        ),
        ShiftAssignment(
            station_id=OPERATOR_SCENARIO_STATION,
            operator_id=op_b.operator_id,
            start_car_index=handover_onset,
            end_car_index=num_cars - 1,
            handover_flagged=False,
        ),
    ]

    return RunConfig(
        run_id=run_id,
        random_seed=seed,
        num_cars=num_cars,
        background_defect_rate=0.0005,
        defect_z_threshold=3.0,
        defect_seeds=[
            DefectSeed(
                id="seed-torque-drift",
                mechanism=DefectMechanism.TORQUE_DRIFT,
                station_id=TORQUE_DRIFT_STATION,
                onset_car_index=torque_onset,
                duration_cars=30,
                severity=4.0,
                surfaces_after_inspections=3,
            ),
        ],
        environment_excursions=[
            EnvironmentExcursion(
                id="exc-paint-booth",
                zone=Zone.PAINT,
                start_car_index=excursion_onset,
                end_car_index=excursion_onset + 20,
                temp_c=35.0,
                surfaces_after_inspections=1,
            ),
        ],
        baseline_temp_c=22.0,
        operator_profiles=operator_profiles,
        operator_shift_schedule=operator_shift_schedule,
    )


def build_dataset(line, store, run_dir: Path):
    """One sample per (car, inspection_station) the car actually reached,
    labeled from inspection.csv, time-ordered by the car's line-entry time."""
    inspection_station_ids = [s.id for s in line.stations if s.is_inspection_station]

    inspection_df = pd.read_csv(run_dir / "inspection.csv")
    label_lookup = {
        (row.car_id, row.station_id): 1 if row.result == "fail" else 0
        for row in inspection_df.itertuples()
    }

    samples = []
    for car_id in store.all_car_ids():
        twin = store.car(car_id)
        for station_id in inspection_station_ids:
            label = label_lookup.get((car_id, station_id))
            if label is None:
                continue  # car never reached this inspection station

            features = build_features(
                car=twin, line=line, store=store, inspection_station_id=station_id
            )
            raw_features = build_raw_features(car=twin, line=line, inspection_station_id=station_id)
            if features is None or raw_features is None:
                continue  # too close to the line start for an 8-ahead prediction

            samples.append(
                {
                    "car_id": car_id,
                    "station_id": station_id,
                    "entry_time": twin.entry_timestamp,
                    "label": label,
                    "features": features,
                    "raw_features": raw_features,
                }
            )

    samples.sort(key=lambda s: s["entry_time"])
    return samples


def time_split(samples):
    n = len(samples)
    train_end = int(n * TRAIN_FRACTION)
    cal_end = train_end + int(n * CALIBRATE_FRACTION)
    return samples[:train_end], samples[train_end:cal_end], samples[cal_end:]


def to_frame(samples, feature_key: str, names: list[str]) -> pd.DataFrame:
    return pd.DataFrame([s[feature_key].values for s in samples], columns=names)


def report(name: str, y_true, y_pred_proba) -> dict:
    y_pred = [1 if p >= 0.5 else 0 for p in y_pred_proba]
    metrics = {
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "auc": roc_auc_score(y_true, y_pred_proba) if len(set(y_true)) > 1 else float("nan"),
    }
    print(
        f"{name:30s} precision={metrics['precision']:.3f} recall={metrics['recall']:.3f} "
        f"f1={metrics['f1']:.3f} auc={metrics['auc']:.3f}"
    )
    return metrics


def summarize(name: str, per_run_metrics: list[dict]) -> None:
    keys = ["precision", "recall", "f1", "auc"]
    means = {k: float(np.nanmean([m[k] for m in per_run_metrics])) for k in keys}
    ranges = {
        k: (min(m[k] for m in per_run_metrics), max(m[k] for m in per_run_metrics)) for k in keys
    }
    parts = [f"{k}={means[k]:.3f} [{ranges[k][0]:.3f}-{ranges[k][1]:.3f}]" for k in keys]
    print(f"{name:30s} " + " ".join(parts))


def main() -> None:
    line = load_line_spec(DEFAULT_LINE_PATH)
    output_root = BACKEND_DIR / "data" / "runs"

    run_train, run_cal, run_test = [], [], []
    per_run_test_sets = []

    for seed in TRAINING_RUN_SEEDS:
        run_id = f"risk_training_run_{seed}"
        config = randomized_run_config(line, run_id, seed)
        artifacts = generate_run(line, config, output_root=output_root)
        store = from_generated_run(line, artifacts.output_dir, config)
        samples = build_dataset(line, store, artifacts.output_dir)

        train, calibrate, test = time_split(samples)
        run_train += train
        run_cal += calibrate
        run_test += test
        per_run_test_sets.append((seed, test))
        print(
            f"run seed={seed}: {len(samples)} samples -> "
            f"train={len(train)} cal={len(calibrate)} test={len(test)}"
        )

    X_train = to_frame(run_train, "features", FEATURE_NAMES)
    y_train = np.array([s["label"] for s in run_train])
    X_cal = to_frame(run_cal, "features", FEATURE_NAMES)
    y_cal = np.array([s["label"] for s in run_cal])

    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.1,
        objective="binary:logistic",
        eval_metric="logloss",
    )
    model.fit(X_train, y_train)

    raw_scores_cal = model.predict_proba(X_cal)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_scores_cal, y_cal)

    X_train_raw = to_frame(run_train, "raw_features", RAW_FEATURE_NAMES)
    ml_only_model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.1,
        objective="binary:logistic",
        eval_metric="logloss",
    )
    ml_only_model.fit(X_train_raw, y_train)

    ooc_index = FEATURE_NAMES.index("spc_out_of_control_fraction")

    twin_metrics, rule_metrics, ml_metrics = [], [], []
    for seed, test in per_run_test_sets:
        if len(test) == 0 or len({s["label"] for s in test}) < 2:
            print(f"run seed={seed}: skipping test evaluation (degenerate label set)")
            continue
        X_test = to_frame(test, "features", FEATURE_NAMES)
        X_test_raw = to_frame(test, "raw_features", RAW_FEATURE_NAMES)
        y_test = np.array([s["label"] for s in test])

        calibrated_test = calibrator.predict(model.predict_proba(X_test)[:, 1])
        rule_based_scores = [1.0 if s["features"].values[ooc_index] > 0 else 0.0 for s in test]
        ml_only_scores = ml_only_model.predict_proba(X_test_raw)[:, 1]

        print(f"\n--- seed={seed} (n={len(test)}, positives={int(y_test.sum())}) ---")
        twin_metrics.append(report("twin-enriched (calibrated)", y_test, calibrated_test))
        rule_metrics.append(report("rule-based (any SPC alarm)", y_test, rule_based_scores))
        ml_metrics.append(report("ML-only (no twin features)", y_test, ml_only_scores))

    print("\n--- Mean [range] across runs ---")
    summarize("twin-enriched (calibrated)", twin_metrics)
    summarize("rule-based (any SPC alarm)", rule_metrics)
    summarize("ML-only (no twin features)", ml_metrics)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.get_booster().save_model(str(MODEL_DIR / "booster.json"))
    (MODEL_DIR / "calibrator.json").write_text(
        json.dumps({"x": raw_scores_cal.tolist(), "y": y_cal.tolist()})
    )
    (MODEL_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "version": "risk_v1",
                "feature_names": FEATURE_NAMES,
                "coverage_threshold": COVERAGE_THRESHOLD,
            },
            indent=2,
        )
    )
    print(f"\nsaved model to {MODEL_DIR}")


if __name__ == "__main__":
    main()
