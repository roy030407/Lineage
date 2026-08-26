"""Tests for lineage.twin.ingest -- the bridge from a generated run's CSVs into
a GenealogyStore."""

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
from lineage.datagen.models import OperatorProfile, RunConfig, ShiftAssignment
from lineage.datagen.run import generate_run
from lineage.twin.ingest import from_generated_run


def _machine() -> MachineSpec:
    return MachineSpec(
        model="M",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )


def make_line() -> LineSpec:
    sensor = SensorSpec(
        id="ST-01-SEN-1",
        kind=SensorKind.TORQUE,
        unit="N.m",
        sample_rate_hz=50.0,
        install_date=date(2020, 1, 1),
        last_calibration_date=date(2024, 1, 1),
        accuracy_class="1.0",
    )
    baseline_a = CommissioningBaseline(
        idle=ConditionStats(mean={"ST-01-SEN-1": 5.0}, std={"ST-01-SEN-1": 1.0}),
        loaded=ConditionStats(mean={"ST-01-SEN-1": 10.0}, std={"ST-01-SEN-1": 2.0}),
    )
    baseline_b = CommissioningBaseline(
        idle=ConditionStats(mean={"torque_nm": 5.0}, std={"torque_nm": 1.0}),
        loaded=ConditionStats(mean={"torque_nm": 10.0}, std={"torque_nm": 2.0}),
    )
    stations = [
        StationSpec(
            id="ST-01",
            name="Instrumented",
            zone=Zone.BODY,
            sequence_index=0,
            sensors=[sensor],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=baseline_a,
            machine=_machine(),
            cost_per_hour=10.0,
            value_add_pct=1.0,
        ),
        StationSpec(
            id="ST-02",
            name="Manual",
            zone=Zone.BODY,
            sequence_index=1,
            sensors=[],
            acquisition_mode=AcquisitionMode.MANUAL,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=baseline_b,
            readable_params=["torque_nm"],
            machine=_machine(),
            cost_per_hour=10.0,
            value_add_pct=1.0,
        ),
    ]
    coords = [
        StationCoordinate(station_id=s.id, x_m=float(i * 10), y_m=0.0)
        for i, s in enumerate(stations)
    ]
    segments = [ConveyorSegment(from_station_id="ST-01", to_station_id="ST-02", distance_m=5.0)]
    return LineSpec(
        plant_name="Test Plant",
        site="Testville",
        stations=stations,
        layout=LayoutSpec(coordinates=coords, segments=segments),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )


def test_ingest_builds_correct_visit_counts_and_order(tmp_path):
    line = make_line()
    config = RunConfig(
        run_id="ingest-test",
        random_seed=1,
        num_cars=6,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[
            OperatorProfile(operator_id="OP-A", bias=0.0, std=0.3),
            OperatorProfile(operator_id="OP-B", bias=1.0, std=0.3),
        ],
        operator_shift_schedule=[
            ShiftAssignment(
                station_id="ST-02", operator_id="OP-A", start_car_index=0, end_car_index=2
            ),
            ShiftAssignment(
                station_id="ST-02",
                operator_id="OP-B",
                start_car_index=3,
                end_car_index=5,
                handover_flagged=True,
            ),
        ],
    )
    artifacts = generate_run(line, config, output_root=tmp_path)
    store = from_generated_run(line, artifacts.output_dir, config)

    assert len(store.all_car_ids()) == 6
    car0 = store.car("CAR-00000")
    assert [v.station_id for v in car0.visits] == ["ST-01", "ST-02"]
    assert car0.visits[1].operator_id == "OP-A"


def test_ingest_sets_handover_flagged_only_on_the_boundary_visit(tmp_path):
    line = make_line()
    config = RunConfig(
        run_id="ingest-test-2",
        random_seed=1,
        num_cars=6,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[
            OperatorProfile(operator_id="OP-A", bias=0.0, std=0.3),
            OperatorProfile(operator_id="OP-B", bias=1.0, std=0.3),
        ],
        operator_shift_schedule=[
            ShiftAssignment(
                station_id="ST-02", operator_id="OP-A", start_car_index=0, end_car_index=2
            ),
            ShiftAssignment(
                station_id="ST-02",
                operator_id="OP-B",
                start_car_index=3,
                end_car_index=5,
                handover_flagged=True,
            ),
        ],
    )
    artifacts = generate_run(line, config, output_root=tmp_path)
    store = from_generated_run(line, artifacts.output_dir, config)

    flagged_visits = []
    for car_id in store.all_car_ids():
        for visit in store.car(car_id).visits:
            if visit.station_id == "ST-02" and visit.handover_flagged is not None:
                flagged_visits.append((car_id, visit.handover_flagged))

    assert flagged_visits == [("CAR-00000", False), ("CAR-00003", True)]
