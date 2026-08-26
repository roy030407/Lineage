"""Tests for lineage.predict.risk; to be filled in alongside real logic."""

from datetime import date, datetime, timedelta

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
from lineage.predict.models import RiskAssessment
from lineage.predict.risk import assess_risk, build_features
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


def make_visit(station_id: str, t: datetime, value: float, dwell_s: float = 10.0) -> StationVisit:
    return StationVisit(
        station_id=station_id,
        entry_time=t,
        exit_time=t + timedelta(seconds=dwell_s),
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


def populate(line: LineSpec, car_id: str, values: dict[str, float]) -> GenealogyStore:
    store = GenealogyStore()
    store.register_car(car_id, "standard", T0)
    for i, station in enumerate(line.stations):
        if station.id in values:
            visit = make_visit(station.id, T0 + timedelta(seconds=i * 10), values[station.id])
            store.record_visit(car_id, visit)
    return store


def test_lookback_is_structurally_enforced(tmp_path):
    """A car with visits extending past the cutoff must produce the exact
    same feature vector as one truncated right at the cutoff -- later visits
    must never leak in, regardless of what's in car.visits."""
    line = make_line(num_stations=12)  # inspection at ST-11, cutoff at ST-03 (11-8)
    inspection_id = "ST-11"

    values_short = {f"ST-{i:02d}": 10.0 + i for i in range(4)}  # ST-00..ST-03
    values_long = dict(values_short)
    values_long.update({f"ST-{i:02d}": 999.0 for i in range(4, 12)})  # extra, should be ignored

    store_short = populate(line, "CAR-SHORT", values_short)
    store_long = populate(line, "CAR-LONG", values_long)

    fv_short = build_features(
        car=store_short.car("CAR-SHORT"), line=line, store=store_short,
        inspection_station_id=inspection_id,
    )
    fv_long = build_features(
        car=store_long.car("CAR-LONG"), line=line, store=store_long,
        inspection_station_id=inspection_id,
    )

    assert fv_short is not None and fv_long is not None
    assert fv_short.values == fv_long.values


def test_returns_none_when_inspection_too_close_to_line_start():
    line = make_line(num_stations=5)  # inspection at ST-04, cutoff = 4-8 < 0
    store = populate(line, "CAR-001", {"ST-00": 10.0})
    fv = build_features(
        car=store.car("CAR-001"), line=line, store=store, inspection_station_id="ST-04"
    )
    assert fv is None


def test_coverage_fraction_drops_when_readings_missing():
    line = make_line(num_stations=10)  # inspection ST-09, cutoff stations ST-00..ST-01
    store_full = populate(line, "CAR-FULL", {"ST-00": 10.0, "ST-01": 10.0})
    store_partial = populate(line, "CAR-PARTIAL", {"ST-00": 10.0})  # ST-01 missing entirely

    fv_full = build_features(
        car=store_full.car("CAR-FULL"), line=line, store=store_full, inspection_station_id="ST-09"
    )
    fv_partial = build_features(
        car=store_partial.car("CAR-PARTIAL"), line=line, store=store_partial,
        inspection_station_id="ST-09",
    )

    assert fv_full.coverage_fraction == 1.0
    assert fv_partial.coverage_fraction < fv_full.coverage_fraction


class _StubModel:
    """A minimal stand-in for RiskModel: assess_risk must short-circuit on
    low coverage before ever calling predict_proba, so this deliberately
    doesn't implement it."""

    coverage_threshold = 0.5
    version = "stub"


def test_unknown_risk_when_coverage_below_threshold():
    line = make_line(num_stations=10)
    store = populate(line, "CAR-001", {})  # no readings at all -> zero coverage
    result = assess_risk(
        car=store.car("CAR-001"),
        line=line,
        store=store,
        inspection_station_id="ST-09",
        model=_StubModel(),
    )
    assert isinstance(result, RiskAssessment)
    assert result.risk_level.value == "unknown_risk"
    assert result.probability is None
