"""Offline training for the risk model. Runtime (lineage.predict.risk) only
ever loads what this script produces; it never trains.

Usage: run with the backend venv's python, from anywhere:
    backend/.venv/Scripts/python.exe scripts/train_risk_model.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from lineage.config.loader import load_line_spec
from lineage.datagen.cli import DEFAULT_LINE_PATH, build_default_run_config
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


def main() -> None:
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)
    config = config.model_copy(update={"run_id": "risk_training_run", "random_seed": 20240915})

    output_root = BACKEND_DIR / "data" / "runs"
    artifacts = generate_run(line, config, output_root=output_root)

    store = from_generated_run(line, artifacts.output_dir, config)
    samples = build_dataset(line, store, artifacts.output_dir)
    print(f"built {len(samples)} (car, inspection_station) samples")

    train, calibrate, test = time_split(samples)
    print(
        f"train={len(train)} calibrate={len(calibrate)} test={len(test)} "
        "(time-ordered, not shuffled)"
    )
    assert max(s["entry_time"] for s in train) <= min(s["entry_time"] for s in calibrate)
    assert max(s["entry_time"] for s in calibrate) <= min(s["entry_time"] for s in test)

    X_train = to_frame(train, "features", FEATURE_NAMES)
    y_train = np.array([s["label"] for s in train])
    X_cal = to_frame(calibrate, "features", FEATURE_NAMES)
    y_cal = np.array([s["label"] for s in calibrate])
    X_test = to_frame(test, "features", FEATURE_NAMES)
    y_test = np.array([s["label"] for s in test])

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

    raw_scores_test = model.predict_proba(X_test)[:, 1]
    calibrated_test = calibrator.predict(raw_scores_test)

    print("\n--- Model comparison (test set) ---")
    report("twin-enriched (calibrated)", y_test, calibrated_test)

    ooc_index = FEATURE_NAMES.index("spc_out_of_control_fraction")
    rule_based_scores = [1.0 if s["features"].values[ooc_index] > 0 else 0.0 for s in test]
    report("rule-based (any SPC alarm)", y_test, rule_based_scores)

    X_train_raw = to_frame(train, "raw_features", RAW_FEATURE_NAMES)
    X_test_raw = to_frame(test, "raw_features", RAW_FEATURE_NAMES)
    ml_only_model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.1,
        objective="binary:logistic",
        eval_metric="logloss",
    )
    ml_only_model.fit(X_train_raw, y_train)
    ml_only_scores = ml_only_model.predict_proba(X_test_raw)[:, 1]
    report("ML-only (no twin features)", y_test, ml_only_scores)

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
