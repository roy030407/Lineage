"""Enforces the project's non-negotiable invariants, line-shape-agnostically:
the station count is never hardcoded, a station without usable sensor coverage
returns UNKNOWN_RISK (never a numeric level, never "safe"), Act proposals stay
within the safety envelope for any deviation input, and metrics with a zero
denominator are None -- never a fabricated 0.0.
"""

from datetime import date, datetime, timedelta

import pytest

from lineage.act.proposals import propose
from lineage.act.validator import validate_proposal
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
    ParamRange,
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)
from lineage.predict.ledger import compute_metrics
from lineage.predict.risk import assess_risk
from lineage.trace.models import ContributionCause, TraceResult
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


def _station(index: int, *, manual: bool = False, inspection: bool = False) -> StationSpec:
    station_id = f"ST-{index:02d}"
    sensor_id = f"{station_id}-SEN-1"
    return StationSpec(
        id=station_id,
        name=f"Station {index}",
        zone=Zone.BODY,
        sequence_index=index,
        sensors=[] if manual else [_sensor(sensor_id)],
        acquisition_mode=AcquisitionMode.MANUAL if manual else AcquisitionMode.INSTRUMENTED,
        is_inspection_station=inspection,
        cycle_time_nominal_s=10.0,
        commissioning_baseline=CommissioningBaseline(
            idle=ConditionStats(mean={sensor_id: 5.0}, std={sensor_id: 1.0}),
            loaded=ConditionStats(mean={sensor_id: 10.0}, std={sensor_id: 2.0}),
        ),
        changeable_params={"line_speed_pct": ParamRange(min=60.0, max=110.0, step=1.0)},
        readable_params=[sensor_id] if manual else [],
        machine=_machine(),
        cost_per_hour=10.0,
        value_add_pct=1.0,
    )


def make_line(num_stations: int, *, manual_indexes: set[int] | None = None) -> LineSpec:
    manual_indexes = manual_indexes or set()
    stations = [
        _station(i, manual=(i in manual_indexes), inspection=(i == num_stations - 1))
        for i in range(num_stations)
    ]
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
        plant_name="Invariant Plant",
        site="Testville",
        stations=stations,
        layout=LayoutSpec(coordinates=coords, segments=segments),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )


@pytest.mark.parametrize("num_stations", [3, 7, 20])
def test_no_hardcoded_station_count_in_line_reshaping(num_stations):
    """Insert and remove must work at any line size and always leave a
    structurally consistent line: contiguous sequence indexes from 0, one
    coordinate per station, and exactly stations-1 conveyor segments."""
    line = make_line(num_stations)

    inserted = line.insert_station(
        _station(999), after_station_id=line.stations[num_stations // 2].id
    )
    removed = inserted.remove_station(inserted.stations[1].id)

    for spec in (inserted, removed):
        indexes = [s.sequence_index for s in sorted(spec.stations, key=lambda s: s.sequence_index)]
        assert indexes == list(range(len(spec.stations)))
        assert len(spec.layout.coordinates) == len(spec.stations)
        assert len(spec.layout.segments) == len(spec.stations) - 1
    assert len(inserted.stations) == num_stations + 1
    assert len(removed.stations) == num_stations


class _StubModel:
    """assess_risk must short-circuit on low coverage before ever calling
    predict_proba, so this deliberately doesn't implement it."""

    coverage_threshold = 0.5
    version = "stub"


def test_sensorless_station_is_unknown_risk_never_numeric():
    """A car with no usable readings must come back UNKNOWN_RISK with
    probability=None -- not LOW, not 0.0, not a guess."""
    line = make_line(10, manual_indexes=set(range(9)))
    store = GenealogyStore()
    store.register_car("CAR-001", "standard", T0)

    result = assess_risk(
        car=store.car("CAR-001"),
        line=line,
        store=store,
        inspection_station_id=line.stations[-1].id,
        model=_StubModel(),
    )

    assert result.risk_level == RiskLevel.UNKNOWN_RISK
    assert result.probability is None


@pytest.mark.parametrize("deviation_z", [-6.0, -3.0, -0.5, 0.0, 0.5, 3.0, 6.0])
def test_act_proposals_always_inside_safety_envelope(deviation_z):
    """Whatever deviation Trace reports, every emitted proposal must pass the
    validator: inside the station range, inside the plant-wide envelope, and
    within the max single-step change."""
    line = make_line(5)
    origin = line.stations[2]
    trace_result = TraceResult(
        car_id="CAR-001",
        originating_station_id=origin.id,
        originating_is_verifiable=True,
        ranked_contributions=[
            ContributionCause(
                station_id=origin.id,
                contribution_score=0.9,
                verifiable=True,
                deviation_z=deviation_z,
            )
        ],
    )

    proposals = propose(trace_result, line)

    assert proposals, "an origin with changeable params must yield a proposal"
    for proposal in proposals:
        validate_proposal(proposal, origin)  # must not raise, for any z


def test_zero_denominator_metrics_are_none_not_zero():
    """No alarms raised -> precision is None; no failures -> recall is None.
    A fabricated 0.0 would silently read as 'measured and terrible'."""
    metrics = compute_metrics([])
    assert metrics.sample_size == 0
    assert metrics.precision is None
    assert metrics.recall is None
    assert metrics.false_alarm_rate is None
    assert metrics.trust_score is None


def test_trace_cohort_never_contains_the_flagged_car():
    """The exposed-cohort query answers 'who ELSE was exposed' -- the flagged
    car itself must never appear in its own cohort."""
    from lineage.trace.lineage_query import find_affected_cars

    line = make_line(3)
    store = GenealogyStore()
    from lineage.twin.car import AmbientConditions, Reading, StationVisit

    for i, car_id in enumerate(["CAR-000", "CAR-001", "CAR-002"]):
        t = T0 + timedelta(minutes=i)
        store.register_car(car_id, "standard", t)
        store.record_visit(
            car_id,
            StationVisit(
                station_id="ST-01",
                entry_time=t,
                exit_time=t + timedelta(seconds=10),
                readings=[
                    Reading(
                        sensor_id="ST-01-SEN-1",
                        quantity="torque",
                        value=20.0,
                        acquisition_mode="instrumented",
                    )
                ],
                machine_wear_state=0.1,
                ambient_conditions=AmbientConditions(temp_c=22.0),
            ),
        )

    affected = find_affected_cars(
        line,
        store,
        originating_station_id="ST-01",
        quantity="ST-01-SEN-1",
        flagged_car_id="CAR-000",
    )

    assert "CAR-000" not in {c.car_id for c in affected}
    assert {c.car_id for c in affected} == {"CAR-001", "CAR-002"}
