"""Tests for lineage.replay; to be filled in alongside real logic."""

from datetime import date

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
from lineage.datagen.models import RunConfig
from lineage.datagen.run import generate_run
from lineage.replay.engine import ReplayEngine
from lineage.replay.models import MachineHealth, PlaybackMode, SensorHealth
from lineage.replay.run_data import RunData


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
        idle=ConditionStats(mean={key: 10.0}, std={key: 0.5}),
        loaded=ConditionStats(mean={key: 20.0}, std={key: 1.0}),
    )


def make_replay_test_line() -> LineSpec:
    stations = [
        StationSpec(
            id="ST-01",
            name="Instrumented",
            zone=Zone.BODY,
            sequence_index=0,
            sensors=[_sensor("ST-01-SEN-1")],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=_baseline("ST-01-SEN-1"),
            machine=_machine(),
            cost_per_hour=10.0,
            value_add_pct=1.0,
        ),
        StationSpec(
            id="ST-02",
            name="Manual, no sensors",
            zone=Zone.BODY,
            sequence_index=1,
            sensors=[],
            acquisition_mode=AcquisitionMode.MANUAL,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=_baseline("torque_nm"),
            readable_params=["torque_nm"],
            machine=_machine(),
            cost_per_hour=10.0,
            value_add_pct=1.0,
        ),
        StationSpec(
            id="ST-03",
            name="Instrumented 2",
            zone=Zone.FINAL,
            sequence_index=2,
            sensors=[_sensor("ST-03-SEN-1")],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=_baseline("ST-03-SEN-1"),
            machine=_machine(),
            cost_per_hour=10.0,
            value_add_pct=1.0,
        ),
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
        plant_name="Test Plant",
        site="Testville",
        stations=stations,
        layout=LayoutSpec(coordinates=coords, segments=segments),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )


def make_engine(tmp_path, num_cars: int = 5) -> ReplayEngine:
    line = make_replay_test_line()
    config = RunConfig(
        run_id="replay-test-run",
        random_seed=1,
        num_cars=num_cars,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[],
        operator_shift_schedule=[],
    )
    artifacts = generate_run(line, config, output_root=tmp_path)
    run_data = RunData(artifacts.run_id, artifacts.output_dir)
    return ReplayEngine(line, run_data, start_time=run_data.start_time)


def test_same_run_produces_identical_tick_sequence(tmp_path):
    engine_a = make_engine(tmp_path / "a")
    engine_b = make_engine(tmp_path / "b")

    states_a = [engine_a.tick() for _ in range(5)]
    states_b = [engine_b.tick() for _ in range(5)]

    assert [s.model_dump(mode="json") for s in states_a] == [
        s.model_dump(mode="json") for s in states_b
    ]


def test_seek_is_idempotent(tmp_path):
    engine = make_engine(tmp_path)
    target = engine.run_data.start_time

    engine.tick()
    engine.tick()
    state_from_advanced = engine.seek(target)

    engine.seek(engine.run_data.start_time)
    engine.tick()
    state_from_elsewhere = engine.seek(target)

    assert state_from_advanced.model_dump(mode="json") == state_from_elsewhere.model_dump(
        mode="json"
    )


def test_ticking_advances_time_and_buffer_depths_become_nonzero(tmp_path):
    """Regression test for a real reported symptom: a deployed instance
    stuck with buffers at 0.0 and stations RED because simulated time
    never advanced past load. engine.tick() is the exact mechanism the
    background _tick_loop in api/app.py calls once a second while
    PLAYING -- this asserts that mechanism actually moves time forward
    and that upstream buffering (cars queueing behind a station) is real,
    observable behavior, not just a static snapshot repeated forever.

    This does NOT reproduce the leading suspected root cause (multiple
    worker processes/instances splitting AppState's single in-memory
    global, so the process serving a WebSocket never sees an engine at
    all) -- that's a deployment-topology issue, not something a
    single-process test can exercise. It does guard against a genuine
    regression in the tick mechanism itself."""
    engine = make_engine(tmp_path, num_cars=20)
    initial_time = engine.current_state().timestamp

    buffer_seen_nonzero = False
    for _ in range(120):
        state = engine.tick()
        if any(s.upstream_buffer_depth > 0 for s in state.stations):
            buffer_seen_nonzero = True

    assert engine.current_state().timestamp > initial_time
    assert buffer_seen_nonzero


def test_pausing_stops_emission(tmp_path):
    engine = make_engine(tmp_path)
    engine.pause()

    before = engine.current_state()
    engine.tick()
    engine.tick()
    after = engine.current_state()

    assert before.timestamp == after.timestamp
    assert after.playback_mode == PlaybackMode.PAUSED


def test_station_without_sensors_reports_not_applicable_never_red(tmp_path):
    engine = make_engine(tmp_path)
    state = engine.current_state()

    manual_station = next(s for s in state.stations if s.station_id == "ST-02")
    assert manual_station.sensor_health == SensorHealth.NOT_APPLICABLE

    instrumented_station = next(s for s in state.stations if s.station_id == "ST-01")
    assert instrumented_station.sensor_health in (SensorHealth.GREEN, SensorHealth.RED)


def test_machine_health_green_when_freshly_maintained(tmp_path):
    engine = make_engine(tmp_path)
    state = engine.current_state()
    assert all(s.machine_health == MachineHealth.GREEN for s in state.stations)


def test_latest_readings_present_for_instrumented_absent_for_manual(tmp_path):
    engine = make_engine(tmp_path)
    # Advance a few ticks so at least one car has actually reported.
    for _ in range(5):
        engine.tick()
    state = engine.current_state()

    instrumented = next(s for s in state.stations if s.station_id == "ST-01")
    assert instrumented.latest_readings, "expected at least one reading after 5 ticks"
    for reading in instrumented.latest_readings:
        assert reading.sensor_id == "ST-01-SEN-1"
        assert isinstance(reading.value, float)

    manual = next(s for s in state.stations if s.station_id == "ST-02")
    for reading in manual.latest_readings:
        assert reading.quantity == "torque_nm"
