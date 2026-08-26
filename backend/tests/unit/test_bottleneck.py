"""Tests for lineage.predict.bottleneck; to be filled in alongside real logic."""

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
from lineage.predict.bottleneck import BottleneckState, forecast_station
from lineage.twin.car import AmbientConditions, StationVisit
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


def make_line() -> LineSpec:
    stations = []
    for station_id in ["ST-A", "ST-B", "ST-C"]:
        sensor_id = f"{station_id}-SEN-1"
        baseline = CommissioningBaseline(
            idle=ConditionStats(mean={sensor_id: 5.0}, std={sensor_id: 1.0}),
            loaded=ConditionStats(mean={sensor_id: 10.0}, std={sensor_id: 2.0}),
        )
        stations.append(
            StationSpec(
                id=station_id,
                name=station_id,
                zone=Zone.BODY,
                sequence_index=len(stations),
                sensors=[_sensor(f"{station_id}-SEN-1")],
                acquisition_mode=AcquisitionMode.INSTRUMENTED,
                cycle_time_nominal_s=10.0,
                commissioning_baseline=baseline,
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


def _visit(station_id: str, entry: datetime, exit_: datetime) -> StationVisit:
    return StationVisit(
        station_id=station_id,
        entry_time=entry,
        exit_time=exit_,
        readings=[],
        machine_wear_state=0.1,
        ambient_conditions=AmbientConditions(temp_c=22.0),
    )


def build_queue_scenario(
    num_cars: int,
    takt_s: float,
    a_dwell_s: float,
    b_dwell_s_by_car: list[float],
    c_dwell_s_by_car: list[float] | None = None,
) -> tuple[GenealogyStore, list[datetime], list[int]]:
    """Builds a realistic single-queue A->B(->C) timeline: each station can
    only start a car once it has exited the previous station AND finished
    the car before it. Returns the store, each car's A-exit timestamp, and
    the buffer depth between A and B (cars that have exited A but not yet
    entered B) sampled at each of those timestamps."""
    store = GenealogyStore()
    a_exit_times = []
    b_entry_times = []
    b_exit_times = []
    prev_b_exit = None
    prev_c_exit = None

    for i in range(num_cars):
        car_id = f"CAR-{i:03d}"
        a_entry = T0 + timedelta(seconds=i * takt_s)
        a_exit = a_entry + timedelta(seconds=a_dwell_s)
        b_entry = max(a_exit, prev_b_exit) if prev_b_exit is not None else a_exit
        b_exit = b_entry + timedelta(seconds=b_dwell_s_by_car[i])

        store.register_car(car_id, "standard", a_entry)
        store.record_visit(car_id, _visit("ST-A", a_entry, a_exit))
        store.record_visit(car_id, _visit("ST-B", b_entry, b_exit))

        if c_dwell_s_by_car is not None:
            c_entry = max(b_exit, prev_c_exit) if prev_c_exit is not None else b_exit
            c_exit = c_entry + timedelta(seconds=c_dwell_s_by_car[i])
            store.record_visit(car_id, _visit("ST-C", c_entry, c_exit))
            prev_c_exit = c_exit

        a_exit_times.append(a_exit)
        b_entry_times.append(b_entry)
        b_exit_times.append(b_exit)
        prev_b_exit = b_exit

    depths_at_a_exit = []
    for t in a_exit_times:
        depth = sum(1 for j in range(num_cars) if a_exit_times[j] <= t < b_entry_times[j])
        depths_at_a_exit.append(depth)

    return store, a_exit_times, depths_at_a_exit


def test_healthy_when_rates_are_balanced():
    store, a_exit_times, _ = build_queue_scenario(
        num_cars=20, takt_s=10.0, a_dwell_s=8.0, b_dwell_s_by_car=[8.0] * 20
    )
    line = make_line()
    forecast = forecast_station(
        line=line, store=store, station_id="ST-A", as_of=a_exit_times[15], lookback_visits=10
    )
    assert forecast.predicted_state == BottleneckState.HEALTHY


def test_forecast_identifies_slowdown_before_buffer_dip_appears():
    """A known station (ST-B) slows down starting at car 10 (feed rate from
    ST-A now exceeds ST-B's service rate). The forecast, evaluated using only
    the first few slowed readings, must flag ST-A as BLOCKED before the
    buffer depth actually reaches a visible dip (>= 3)."""
    num_cars = 30
    b_dwell = [8.0] * 10 + [15.0] * (num_cars - 10)  # slows down at car index 10

    store, a_exit_times, depths = build_queue_scenario(
        num_cars=num_cars, takt_s=10.0, a_dwell_s=8.0, b_dwell_s_by_car=b_dwell
    )
    line = make_line()

    dip_threshold = 3
    first_dip_index = next(i for i, d in enumerate(depths) if d >= dip_threshold)
    assert depths[first_dip_index] >= dip_threshold

    # Evaluate the forecast early: only a few cars past the slowdown's onset,
    # well before the buffer has visibly grown.
    evaluation_index = 14
    assert depths[evaluation_index] < dip_threshold, "test setup: dip must not have appeared yet"
    assert evaluation_index < first_dip_index, "test setup: evaluation must precede the real dip"

    # A short lookback (5, not the default 15) so the forecast is responsive
    # to the last few cars' trend rather than averaging it away against
    # pre-slowdown history still sitting in a longer window.
    forecast = forecast_station(
        line=line,
        store=store,
        station_id="ST-A",
        as_of=a_exit_times[evaluation_index],
        lookback_visits=5,
        horizon_minutes=60.0,
    )

    assert forecast.predicted_state == BottleneckState.BLOCKED
    assert forecast.contributing_upstream_station == "ST-B"
    assert forecast.minutes_to_onset is not None
    # This evaluation point precedes the real dip (asserted above as a setup
    # precondition) -- the forecast firing BLOCKED here, using only data
    # available up to this point, is the early warning itself.
    assert a_exit_times[evaluation_index] < a_exit_times[first_dip_index]


def test_unknown_station_returns_healthy_with_zero_confidence():
    store = GenealogyStore()
    line = make_line()
    forecast = forecast_station(line=line, store=store, station_id="ST-NOPE", as_of=T0)
    assert forecast.predicted_state == BottleneckState.HEALTHY
    assert forecast.confidence == 0.0


def test_last_station_has_no_downstream_gap_to_be_blocked_by():
    """ST-C is the line's last station: with balanced rates on its only
    (upstream) gap, it must report HEALTHY on real, matching data -- not
    HEALTHY merely because there's no data for it at all."""
    store, a_exit_times, _ = build_queue_scenario(
        num_cars=15,
        takt_s=10.0,
        a_dwell_s=8.0,
        b_dwell_s_by_car=[8.0] * 15,
        c_dwell_s_by_car=[8.0] * 15,
    )
    line = make_line()
    forecast = forecast_station(
        line=line, store=store, station_id="ST-C", as_of=a_exit_times[10], lookback_visits=10
    )
    assert forecast.predicted_state == BottleneckState.HEALTHY
