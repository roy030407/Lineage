"""Tests for lineage.trace; to be filled in alongside real logic."""

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
from lineage.trace.lineage_query import find_affected_cars, trace
from lineage.trace.rootcause import find_originating_station, rank_contributions, score_visits
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


def _instrumented_station(station_id: str, sequence_index: int) -> StationSpec:
    sensor_id = f"{station_id}-SEN-1"
    return StationSpec(
        id=station_id,
        name=station_id,
        zone=Zone.BODY,
        sequence_index=sequence_index,
        sensors=[
            SensorSpec(
                id=sensor_id,
                kind=SensorKind.TORQUE,
                unit="N.m",
                sample_rate_hz=50.0,
                install_date=date(2020, 1, 1),
                last_calibration_date=date(2024, 1, 1),
                accuracy_class="1.0",
            )
        ],
        acquisition_mode=AcquisitionMode.INSTRUMENTED,
        cycle_time_nominal_s=10.0,
        commissioning_baseline=CommissioningBaseline(
            idle=ConditionStats(mean={sensor_id: 5.0}, std={sensor_id: 1.0}),
            loaded=ConditionStats(mean={sensor_id: 10.0}, std={sensor_id: 2.0}),
        ),
        machine=_machine(),
        cost_per_hour=10.0,
        value_add_pct=1.0,
    )


def make_line(station_ids: list[str]) -> LineSpec:
    stations = [_instrumented_station(sid, i) for i, sid in enumerate(station_ids)]
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


def _visit(station_id: str, t: datetime, value: float | None) -> StationVisit:
    readings = (
        []
        if value is None
        else [
            Reading(
                sensor_id=f"{station_id}-SEN-1",
                quantity="torque",
                value=value,
                acquisition_mode="instrumented",
            )
        ]
    )
    return StationVisit(
        station_id=station_id,
        entry_time=t,
        exit_time=t + timedelta(seconds=10),
        readings=readings,
        machine_wear_state=0.1,
        ambient_conditions=AmbientConditions(temp_c=22.0),
    )


def test_finds_earliest_verifiable_exceeding_station():
    line = make_line(["ST-01", "ST-02", "ST-03", "ST-04"])
    store = GenealogyStore()
    store.register_car("CAR-001", "standard", T0)
    # ST-02 deviates (z=5), ST-04 also deviates (z=4) -- the earlier one wins.
    store.record_visit("CAR-001", _visit("ST-01", T0, 10.0))  # normal, z=0
    store.record_visit("CAR-001", _visit("ST-02", T0 + timedelta(seconds=10), 20.0))  # z=5
    store.record_visit("CAR-001", _visit("ST-03", T0 + timedelta(seconds=20), 10.0))  # normal
    store.record_visit("CAR-001", _visit("ST-04", T0 + timedelta(seconds=30), 18.0))  # z=4

    car = store.car("CAR-001")
    deviations = score_visits(line, store, car, up_to_station_id="ST-04")
    origin = find_originating_station(deviations)

    assert origin is not None
    assert origin.station_id == "ST-02"
    assert origin.verifiable is True


def test_falls_back_to_unverifiable_when_nothing_verifiable_exceeds():
    line = make_line(["ST-01", "ST-02", "ST-03"])
    store = GenealogyStore()
    store.register_car("CAR-001", "standard", T0)
    store.record_visit("CAR-001", _visit("ST-01", T0, None))  # no reading -> unverifiable
    store.record_visit("CAR-001", _visit("ST-02", T0 + timedelta(seconds=10), 10.0))  # normal
    store.record_visit("CAR-001", _visit("ST-03", T0 + timedelta(seconds=20), 10.5))  # normal

    car = store.car("CAR-001")
    deviations = score_visits(line, store, car, up_to_station_id="ST-03")
    origin = find_originating_station(deviations)

    assert origin is not None
    assert origin.station_id == "ST-01"
    assert origin.verifiable is False


def test_ranked_contributions_never_eliminates_unverifiable_stations():
    line = make_line(["ST-01", "ST-02"])
    store = GenealogyStore()
    store.register_car("CAR-001", "standard", T0)
    store.record_visit("CAR-001", _visit("ST-01", T0, None))
    store.record_visit("CAR-001", _visit("ST-02", T0 + timedelta(seconds=10), 20.0))

    car = store.car("CAR-001")
    deviations = score_visits(line, store, car, up_to_station_id="ST-02")
    ranked = rank_contributions(deviations)

    station_ids = {c.station_id for c in ranked}
    assert station_ids == {"ST-01", "ST-02"}
    unverifiable_entry = next(c for c in ranked if c.station_id == "ST-01")
    assert unverifiable_entry.verifiable is False
    assert unverifiable_entry.contribution_score > 0  # never zero, never eliminated


def test_affected_cars_finds_similar_deviations_in_window_only():
    line = make_line(["ST-01", "ST-02"])
    store = GenealogyStore()
    # 5 cars through ST-02: two share the flagged car's extreme deviation,
    # two are normal, and the flagged car itself.
    values = {"CAR-000": 20.0, "CAR-001": 19.5, "CAR-002": 10.0, "CAR-003": 10.2, "CAR-004": 20.5}
    for i, (car_id, value) in enumerate(values.items()):
        t = T0 + timedelta(minutes=i)
        store.register_car(car_id, "standard", t)
        store.record_visit(car_id, _visit("ST-01", t, 10.0))
        store.record_visit(car_id, _visit("ST-02", t + timedelta(seconds=10), value))

    affected = find_affected_cars(
        line,
        store,
        originating_station_id="ST-02",
        quantity="ST-02-SEN-1",
        flagged_car_id="CAR-000",
    )
    affected_ids = {c.car_id for c in affected}

    assert "CAR-001" in affected_ids
    assert "CAR-004" in affected_ids
    assert "CAR-002" not in affected_ids
    assert "CAR-003" not in affected_ids


def test_trace_end_to_end_returns_full_result():
    line = make_line(["ST-01", "ST-02", "ST-03"])
    store = GenealogyStore()
    store.register_car("CAR-001", "standard", T0)
    store.record_visit("CAR-001", _visit("ST-01", T0, 10.0))
    store.record_visit("CAR-001", _visit("ST-02", T0 + timedelta(seconds=10), 20.0))
    store.record_visit("CAR-001", _visit("ST-03", T0 + timedelta(seconds=20), 10.0))

    result = trace(line=line, store=store, car_id="CAR-001", flagged_at_station_id="ST-03")

    assert result.originating_station_id == "ST-02"
    assert result.originating_is_verifiable is True
    assert {c.station_id for c in result.ranked_contributions} == {"ST-01", "ST-02", "ST-03"}
