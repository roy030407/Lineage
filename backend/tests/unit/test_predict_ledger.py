"""Tests for lineage.predict.ledger: build/resolve, metrics, and trend."""

from datetime import date, datetime, timedelta
from pathlib import Path

from lineage.common.types import RiskLevel
from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    ConveyorSegment,
    EnvironmentEnvelope,
    LayoutSpec,
    LineSpec,
    MachineSpec,
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)
from lineage.predict.ledger import (
    PredictionOutcome,
    PredictionRecord,
    build_ledger_from_run,
    classify_post_intervention_trend,
    compute_metrics,
)
from lineage.twin.car import AmbientConditions, Reading, StationVisit
from lineage.twin.genealogy import GenealogyStore

T0 = datetime(2024, 1, 1, 8, 0)


def _machine() -> MachineSpec:
    return MachineSpec(
        model="M",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )


def _sensor(id_: str) -> SensorSpec:
    return SensorSpec(
        id=id_,
        kind=SensorKind.TORQUE,
        unit="N.m",
        sample_rate_hz=50.0,
        install_date=date(2020, 1, 1),
        last_calibration_date=date(2024, 1, 1),
        accuracy_class="1.0",
    )


def _baseline(key: str) -> CommissioningBaseline:
    return CommissioningBaseline(
        idle=ConditionStats(mean={key: 5.0}, std={key: 1.0}),
        loaded=ConditionStats(mean={key: 10.0}, std={key: 2.0}),
    )


def make_line(num_stations: int) -> LineSpec:
    """The last station is the inspection station -- mirrors
    test_predict_risk.py's make_line exactly (kept local rather than
    imported, matching this codebase's convention of self-contained test
    helpers per file)."""
    stations = []
    for i in range(num_stations):
        station_id = f"ST-{i:02d}"
        sensor_id = f"{station_id}-SEN-1"
        stations.append(
            StationSpec(
                id=station_id,
                name=f"Station {i}",
                zone=Zone.BODY,
                sequence_index=i,
                sensors=[_sensor(sensor_id)],
                acquisition_mode=AcquisitionMode.INSTRUMENTED,
                is_inspection_station=(i == num_stations - 1),
                cycle_time_nominal_s=10.0,
                commissioning_baseline=_baseline(sensor_id),
                machine=_machine(),
                cost_per_hour=10.0,
                value_add_pct=1.0,
            )
        )
    coords = [
        StationCoordinate(station_id=s.id, x_m=float(i * 10), y_m=0.0)
        for i, s in enumerate(stations)
    ]
    segments = [
        ConveyorSegment(
            from_station_id=stations[i].id, to_station_id=stations[i + 1].id, distance_m=5.0
        )
        for i in range(len(stations) - 1)
    ]
    return LineSpec(
        plant_name="Test Plant",
        site="Testville",
        stations=stations,
        layout=LayoutSpec(coordinates=coords, segments=segments),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )


def make_visit(station_id: str, t: datetime, value: float) -> StationVisit:
    return StationVisit(
        station_id=station_id,
        entry_time=t,
        exit_time=t + timedelta(seconds=10),
        readings=[
            Reading(
                sensor_id=f"{station_id}-SEN-1",
                quantity="torque",
                value=value,
                acquisition_mode="instrumented",
            )
        ],
        machine_wear_state=0.1,
        ambient_conditions=AmbientConditions(temp_c=22.0),
    )


def populate(line: LineSpec, car_id: str) -> GenealogyStore:
    """Full-coverage history through the inspection station -- mirrors the
    "values_short" recipe from test_predict_risk.py's lookback test, known
    to produce a non-None, full-coverage feature vector."""
    store = GenealogyStore()
    store.register_car(car_id, "standard", T0)
    for i, station in enumerate(line.stations):
        visit = make_visit(station.id, T0 + timedelta(seconds=i * 10), 10.0 + i)
        store.record_visit(car_id, visit)
    return store


class _FixedProbabilityModel:
    """A RiskModel stand-in with a controllable, fixed prediction."""

    def __init__(self, probability: float, version: str = "test-v1") -> None:
        self._probability = probability
        self.coverage_threshold = 0.0
        self.version = version

    def predict_proba(self, features) -> float:  # noqa: ANN001 -- FeatureVector, kept loose
        return self._probability


def _write_inspection_csv(run_dir: Path, rows: list[tuple[str, str, str]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = ["timestamp,car_id,station_id,result,defect_type"]
    for i, (car_id, station_id, result) in enumerate(rows):
        ts = T0 + timedelta(minutes=i)
        lines.append(f"{ts.isoformat()},{car_id},{station_id},{result},")
    (run_dir / "inspection.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_high_risk_alarm_that_fails_is_materialized(tmp_path):
    line = make_line(num_stations=12)  # inspection at ST-11
    store = populate(line, "CAR-001")
    _write_inspection_csv(tmp_path, [("CAR-001", "ST-11", "fail")])

    ledger = build_ledger_from_run(line, store, tmp_path, _FixedProbabilityModel(0.9))
    records = ledger.all_records()

    assert len(records) == 1
    assert records[0].risk_level == RiskLevel.HIGH
    assert records[0].outcome == PredictionOutcome.MATERIALIZED
    assert records[0].actual_result == "fail"


def test_high_risk_alarm_that_passes_is_not_materialized(tmp_path):
    line = make_line(num_stations=12)
    store = populate(line, "CAR-001")
    _write_inspection_csv(tmp_path, [("CAR-001", "ST-11", "pass")])

    ledger = build_ledger_from_run(line, store, tmp_path, _FixedProbabilityModel(0.9))
    records = ledger.all_records()

    assert records[0].outcome == PredictionOutcome.NOT_MATERIALIZED


def test_low_risk_prediction_is_never_materialized_even_if_car_fails(tmp_path):
    line = make_line(num_stations=12)
    store = populate(line, "CAR-001")
    _write_inspection_csv(tmp_path, [("CAR-001", "ST-11", "fail")])

    ledger = build_ledger_from_run(line, store, tmp_path, _FixedProbabilityModel(0.1))
    records = ledger.all_records()

    assert records[0].risk_level == RiskLevel.LOW
    assert records[0].outcome == PredictionOutcome.NOT_MATERIALIZED


def test_car_never_reaching_inspection_station_is_skipped(tmp_path):
    line = make_line(num_stations=12)
    store = populate(line, "CAR-001")
    _write_inspection_csv(tmp_path, [])  # no inspection row at all for this car

    ledger = build_ledger_from_run(line, store, tmp_path, _FixedProbabilityModel(0.9))
    assert ledger.all_records() == []


def _record(
    risk_level: RiskLevel, actual_result: str, station_id="ST-01", t=T0
) -> PredictionRecord:
    return PredictionRecord(
        car_id="CAR-X",
        station_id=station_id,
        model_version="test-v1",
        risk_level=risk_level,
        probability=0.9 if risk_level == RiskLevel.HIGH else 0.1,
        confidence=1.0,
        predicted_at=t,
        outcome=(
            PredictionOutcome.MATERIALIZED
            if risk_level == RiskLevel.HIGH and actual_result == "fail"
            else PredictionOutcome.NOT_MATERIALIZED
        ),
        resolved_at=t,
        actual_result=actual_result,
    )


def test_compute_metrics_confusion_matrix_and_rates():
    records = [
        _record(RiskLevel.HIGH, "fail"),  # TP
        _record(RiskLevel.HIGH, "fail"),  # TP
        _record(RiskLevel.HIGH, "pass"),  # FP
        _record(RiskLevel.LOW, "fail"),  # FN
        _record(RiskLevel.LOW, "pass"),  # TN
        _record(RiskLevel.LOW, "pass"),  # TN
    ]
    metrics = compute_metrics(records)

    assert metrics.sample_size == 6
    assert (metrics.true_positive, metrics.false_positive) == (2, 1)
    assert (metrics.true_negative, metrics.false_negative) == (2, 1)
    assert metrics.precision == 2 / 3
    assert metrics.recall == 2 / 3
    assert metrics.false_alarm_rate == 1 / 3
    assert metrics.trust_score == 2 / 3  # F1 == precision == recall here


def test_compute_metrics_returns_none_rates_when_no_alarms_and_no_failures():
    records = [_record(RiskLevel.LOW, "pass"), _record(RiskLevel.LOW, "pass")]
    metrics = compute_metrics(records)

    assert metrics.precision is None  # no alarms raised at all: 0/0, not 0.0
    assert metrics.recall is None  # no actual failures: 0/0, not 0.0
    assert metrics.trust_score is None


def test_compute_metrics_filters_by_station_and_model():
    records = [
        _record(RiskLevel.HIGH, "fail", station_id="ST-01"),
        PredictionRecord(
            car_id="CAR-Y",
            station_id="ST-02",
            model_version="other-model",
            risk_level=RiskLevel.HIGH,
            probability=0.9,
            confidence=1.0,
            predicted_at=T0,
            outcome=PredictionOutcome.NOT_MATERIALIZED,
            resolved_at=T0,
            actual_result="pass",
        ),
    ]
    only_st01 = compute_metrics(records, station_id="ST-01")
    assert only_st01.sample_size == 1

    only_other_model = compute_metrics(records, model_version="other-model")
    assert only_other_model.sample_size == 1
    assert only_other_model.true_positive == 0


def test_pending_records_are_excluded_from_metrics():
    pending = PredictionRecord(
        car_id="CAR-Z",
        station_id="ST-01",
        model_version="test-v1",
        risk_level=RiskLevel.HIGH,
        probability=0.9,
        confidence=1.0,
        predicted_at=T0,
    )
    assert pending.outcome == PredictionOutcome.PENDING
    metrics = compute_metrics([pending])
    assert metrics.sample_size == 0


def test_trend_improving_when_trust_score_rises():
    intervention = T0 + timedelta(hours=1)
    # A mix of hits and misses before, so trust_score is well-defined on both sides.
    before = [
        _record(
            RiskLevel.HIGH,
            "fail" if i % 2 == 0 else "pass",
            t=intervention - timedelta(minutes=i + 1),
        )
        for i in range(10)
    ]
    after = [
        _record(RiskLevel.HIGH, "fail", t=intervention + timedelta(minutes=i + 1))
        for i in range(10)
    ]

    trend = classify_post_intervention_trend(before + after, "ST-01", intervention, window_size=10)
    assert trend == "improving"


def test_trend_worsening_when_trust_score_falls():
    intervention = T0 + timedelta(hours=1)
    before = [
        _record(RiskLevel.HIGH, "fail", t=intervention - timedelta(minutes=i + 1))
        for i in range(10)
    ]
    after = [
        _record(
            RiskLevel.HIGH,
            "fail" if i % 2 == 0 else "pass",
            t=intervention + timedelta(minutes=i + 1),
        )
        for i in range(10)
    ]

    trend = classify_post_intervention_trend(before + after, "ST-01", intervention, window_size=10)
    assert trend == "worsening"


def test_trend_stagnant_when_trust_score_barely_changes():
    intervention = T0 + timedelta(hours=1)
    before = [
        _record(RiskLevel.HIGH, "fail", t=intervention - timedelta(minutes=i + 1))
        for i in range(10)
    ]
    after = [
        _record(RiskLevel.HIGH, "fail", t=intervention + timedelta(minutes=i + 1))
        for i in range(10)
    ]

    trend = classify_post_intervention_trend(before + after, "ST-01", intervention, window_size=10)
    assert trend == "stagnant"


def test_trend_returns_none_with_insufficient_data():
    intervention = T0 + timedelta(hours=1)
    before = [_record(RiskLevel.HIGH, "fail", t=intervention - timedelta(minutes=1))]
    after = [_record(RiskLevel.HIGH, "fail", t=intervention + timedelta(minutes=1))]

    trend = classify_post_intervention_trend(before + after, "ST-01", intervention, window_size=10)
    assert trend is None
