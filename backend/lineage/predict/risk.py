"""Feature builder from a CarTwin's history so far, plus the trained-model
loader and runtime risk assessment. Runtime never trains -- see
scripts/train_risk_model.py for that."""

import json
from datetime import datetime
from pathlib import Path

import xgboost as xgb
from sklearn.isotonic import IsotonicRegression

from lineage.common.types import RiskLevel
from lineage.config.specs import LineSpec, StationSpec
from lineage.predict.models import FeatureVector, RiskAssessment
from lineage.predict.spc import SPCState, evaluate_spc
from lineage.twin.car import CarTwin
from lineage.twin.genealogy import GenealogyStore

FEATURE_NAMES = [
    "spc_out_of_control_fraction",
    "spc_max_out_of_control_confidence",
    "spc_environment_invalid_fraction",
    "dwell_deviation_max",
    "dwell_deviation_mean",
    "machine_wear_state_max",
    "machine_wear_state_mean",
    "spc_recalibrating_fraction",
    "ambient_deviation_max",
    "upstream_cumulative_deviation_mean",
]
"""All rates/maxima, deliberately never raw counts or sums: the number of
contributing stations varies hugely by inspection target (~8 for the first
inspection point, ~30+ for the last), so an unnormalized count or sum would
leak *which inspection target this is* rather than measuring genuine
anomaly -- a real confound found by inspecting per-label feature means during
development, not a hypothetical concern."""

RAW_FEATURE_NAMES = ["raw_value_mean", "raw_value_max", "raw_value_min", "raw_value_missing_count"]

DEFAULT_COVERAGE_THRESHOLD = 0.5
DEFAULT_LOOKBACK_STATIONS = 8


def _representative_quantity(station: StationSpec) -> str | None:
    if station.sensors:
        return station.sensors[0].id
    if station.readable_params:
        return station.readable_params[0]
    return None


def _history_for_station(
    store: GenealogyStore, station_id: str, quantity: str, up_to: datetime
) -> list[tuple[datetime, float]]:
    car_ids = store.cars_through(station_id, datetime.min, up_to)
    history = []
    for car_id in car_ids:
        visit = next((v for v in store.car(car_id).visits if v.station_id == station_id), None)
        if visit is None:
            continue
        reading = next(
            (r for r in visit.readings if r.sensor_id == quantity or r.quantity == quantity), None
        )
        if reading is not None:
            history.append((visit.entry_time, reading.value))
    history.sort(key=lambda pair: pair[0])
    return history


def _shift_changes_for_station(
    store: GenealogyStore, station_id: str, up_to: datetime
) -> list[tuple[datetime, bool]]:
    car_ids = store.cars_through(station_id, datetime.min, up_to)
    changes = []
    for car_id in car_ids:
        visit = next((v for v in store.car(car_id).visits if v.station_id == station_id), None)
        if visit is not None and visit.handover_flagged is not None:
            changes.append((visit.entry_time, visit.handover_flagged))
    changes.sort(key=lambda pair: pair[0])
    return changes


def _ambient_deviation(visit_temp_c: float, line: LineSpec) -> float:
    envelope = line.environment_envelope
    if visit_temp_c > envelope.temp_max_c:
        return visit_temp_c - envelope.temp_max_c
    if visit_temp_c < envelope.temp_min_c:
        return envelope.temp_min_c - visit_temp_c
    return 0.0


def _contributing_station_ids(
    line: LineSpec, inspection_station_id: str, lookback_stations: int
) -> list[str] | None:
    station_order = [s.id for s in line.stations]
    if inspection_station_id not in station_order:
        return None
    inspection_index = station_order.index(inspection_station_id)
    cutoff_index = inspection_index - lookback_stations
    if cutoff_index < 0:
        return None
    return station_order[: cutoff_index + 1]


def build_features(
    *,
    car: CarTwin,
    line: LineSpec,
    store: GenealogyStore,
    inspection_station_id: str,
    lookback_stations: int = DEFAULT_LOOKBACK_STATIONS,
) -> FeatureVector | None:
    """Builds the twin-enriched feature vector for predicting whether `car`
    will fail inspection at `inspection_station_id`, using only stations at
    least `lookback_stations` upstream of it -- this is a hard slice on
    station order, not something the caller can accidentally bypass by
    handing over a car with more history than that."""
    contributing_ids = _contributing_station_ids(line, inspection_station_id, lookback_stations)
    if contributing_ids is None:
        return None

    station_by_id = {s.id: s for s in line.stations}
    visits_by_station = {v.station_id: v for v in car.visits}

    spc_ooc_count = 0
    spc_ooc_confidences: list[float] = []
    spc_env_invalid_count = 0
    spc_recalibrating_count = 0
    dwell_devs: list[float] = []
    wear_states: list[float] = []
    ambient_devs: list[float] = []
    cumulative_deviation = 0.0
    covered = 0

    for station_id in contributing_ids:
        visit = visits_by_station.get(station_id)
        if visit is None:
            continue
        station = station_by_id[station_id]

        quantity = _representative_quantity(station)
        contributed = False
        if quantity is not None:
            history = _history_for_station(store, station_id, quantity, visit.entry_time)
            if history:
                shift_changes = _shift_changes_for_station(store, station_id, visit.entry_time)
                verdict = evaluate_spc(
                    station=station,
                    quantity=quantity,
                    history=history,
                    shift_changes=shift_changes,
                    ambient_c=visit.ambient_conditions.temp_c,
                    envelope=line.environment_envelope,
                )
                if verdict.state != SPCState.UNKNOWN:
                    contributed = True
                    if verdict.state == SPCState.OUT_OF_CONTROL:
                        spc_ooc_count += 1
                        spc_ooc_confidences.append(verdict.confidence)
                    elif verdict.state == SPCState.ENVIRONMENT_INVALID:
                        spc_env_invalid_count += 1
                    if verdict.recalibrating:
                        spc_recalibrating_count += 1

        dwell_dev = abs(
            (visit.dwell_time_s - station.cycle_time_nominal_s) / station.cycle_time_nominal_s
        )
        dwell_devs.append(dwell_dev)
        wear_states.append(visit.machine_wear_state)

        ambient_dev = _ambient_deviation(visit.ambient_conditions.temp_c, line)
        ambient_devs.append(ambient_dev)
        cumulative_deviation += dwell_dev + ambient_dev

        if contributed or visit.readings:
            covered += 1

    expected = len(contributing_ids)
    coverage_fraction = covered / expected if expected else 0.0

    values = [
        spc_ooc_count / expected if expected else 0.0,
        max(spc_ooc_confidences, default=0.0),
        spc_env_invalid_count / expected if expected else 0.0,
        max(dwell_devs, default=0.0),
        (sum(dwell_devs) / len(dwell_devs)) if dwell_devs else 0.0,
        max(wear_states, default=0.0),
        (sum(wear_states) / len(wear_states)) if wear_states else 0.0,
        spc_recalibrating_count / expected if expected else 0.0,
        max(ambient_devs, default=0.0),
        cumulative_deviation / expected if expected else 0.0,
    ]

    return FeatureVector(
        car_id=car.car_id,
        target_station_id=inspection_station_id,
        feature_names=FEATURE_NAMES,
        values=values,
        coverage_fraction=coverage_fraction,
    )


def build_raw_features(
    *,
    car: CarTwin,
    line: LineSpec,
    inspection_station_id: str,
    lookback_stations: int = DEFAULT_LOOKBACK_STATIONS,
) -> FeatureVector | None:
    """The ML-only baseline's feature builder: raw sensor values at
    contributing stations only, no twin-derived context (no dwell/wear/
    ambient/operator features, no cross-car SPC history). Used only for the
    training script's baseline comparison, never by runtime assess_risk."""
    contributing_ids = _contributing_station_ids(line, inspection_station_id, lookback_stations)
    if contributing_ids is None:
        return None

    station_by_id = {s.id: s for s in line.stations}
    visits_by_station = {v.station_id: v for v in car.visits}

    raw_values: list[float] = []
    missing = 0
    for station_id in contributing_ids:
        visit = visits_by_station.get(station_id)
        station = station_by_id[station_id]
        quantity = _representative_quantity(station)
        reading = None
        if visit is not None and quantity is not None:
            reading = next(
                (r for r in visit.readings if r.sensor_id == quantity or r.quantity == quantity),
                None,
            )
        if reading is None:
            missing += 1
        else:
            raw_values.append(reading.value)

    expected = len(contributing_ids)
    coverage_fraction = (expected - missing) / expected if expected else 0.0

    values = [
        (sum(raw_values) / len(raw_values)) if raw_values else 0.0,
        max(raw_values, default=0.0),
        min(raw_values, default=0.0),
        float(missing),
    ]

    return FeatureVector(
        car_id=car.car_id,
        target_station_id=inspection_station_id,
        feature_names=RAW_FEATURE_NAMES,
        values=values,
        coverage_fraction=coverage_fraction,
    )


class RiskModel:
    """Loads a saved booster + calibrator. Never trains -- see
    scripts/train_risk_model.py for that."""

    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.booster = xgb.Booster()
        self.booster.load_model(str(model_dir / "booster.json"))

        calibration_path = model_dir / "calibrator.json"
        calibration_data = json.loads(calibration_path.read_text())
        self.calibrator = IsotonicRegression(out_of_bounds="clip")
        self.calibrator.fit(calibration_data["x"], calibration_data["y"])

        manifest = json.loads((model_dir / "manifest.json").read_text())
        self.feature_names: list[str] = manifest["feature_names"]
        self.version: str = manifest["version"]
        self.coverage_threshold: float = manifest.get(
            "coverage_threshold", DEFAULT_COVERAGE_THRESHOLD
        )

    def predict_proba(self, features: FeatureVector) -> float:
        dmatrix = xgb.DMatrix([features.values], feature_names=self.feature_names)
        raw_score = float(self.booster.predict(dmatrix)[0])
        return float(self.calibrator.predict([raw_score])[0])


def assess_risk(
    *,
    car: CarTwin,
    line: LineSpec,
    store: GenealogyStore,
    inspection_station_id: str,
    model: RiskModel,
    lookback_stations: int = DEFAULT_LOOKBACK_STATIONS,
) -> RiskAssessment:
    features = build_features(
        car=car,
        line=line,
        store=store,
        inspection_station_id=inspection_station_id,
        lookback_stations=lookback_stations,
    )
    if features is None or features.coverage_fraction < model.coverage_threshold:
        return RiskAssessment(
            car_id=car.car_id,
            station_id=inspection_station_id,
            risk_level=RiskLevel.UNKNOWN_RISK,
            probability=None,
            confidence=0.0,
            coverage_fraction=features.coverage_fraction if features is not None else 0.0,
            model_version=model.version,
        )

    probability = model.predict_proba(features)
    if probability < 0.33:
        risk_level = RiskLevel.LOW
    elif probability < 0.66:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.HIGH

    confidence = features.coverage_fraction

    return RiskAssessment(
        car_id=car.car_id,
        station_id=inspection_station_id,
        risk_level=risk_level,
        probability=probability,
        confidence=confidence,
        coverage_fraction=features.coverage_fraction,
        model_version=model.version,
    )
