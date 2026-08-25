"""Tests for lineage.datagen; to be filled in alongside real logic."""

from datetime import date, datetime

import pandas as pd
import pytest

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
from lineage.datagen.generators import (
    elapsed_days_since_maintenance,
    operator_bias_for_car,
    wear_z,
)
from lineage.datagen.ground_truth import build_ground_truth_and_inspections
from lineage.datagen.models import (
    DefectMechanism,
    DefectSeed,
    EnvironmentExcursion,
    OperatorProfile,
    RunConfig,
    ShiftAssignment,
)
from lineage.datagen.run import generate_run
from lineage.datagen.writer import _derive_buffer_events, simulate_run


def _machine(model="M", install_year=2020, interval_days=90, shape="linear") -> MachineSpec:
    return MachineSpec(
        model=model,
        install_year=install_year,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=interval_days,
        wear_curve_shape=shape,
    )


def _sensor(id_, kind) -> SensorSpec:
    return SensorSpec(
        id=id_,
        kind=kind,
        unit="u",
        sample_rate_hz=1.0,
        install_date=date(2020, 1, 1),
        last_calibration_date=date(2024, 1, 1),
        accuracy_class="1.0",
    )


def _baseline(keys: list[str]) -> CommissioningBaseline:
    return CommissioningBaseline(
        idle=ConditionStats(mean={k: 10.0 for k in keys}, std={k: 0.5 for k in keys}),
        loaded=ConditionStats(mean={k: 20.0 for k in keys}, std={k: 1.0 for k in keys}),
    )


def make_test_line(inspection_ids: set[str] | None = None) -> LineSpec:
    """A small 5-station line: 1 instrumented (torque origin), 1 manual, 3 more
    instrumented with the last two flagged as inspection points."""
    inspection_ids = inspection_ids or {"ST-04", "ST-05"}

    stations = [
        StationSpec(
            id="ST-01",
            name="Origin",
            zone=Zone.BODY,
            sequence_index=0,
            sensors=[_sensor("ST-01-SEN-1", SensorKind.TORQUE)],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            is_inspection_station="ST-01" in inspection_ids,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=_baseline(["ST-01-SEN-1"]),
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
            is_inspection_station="ST-02" in inspection_ids,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=_baseline(["torque_nm"]),
            changeable_params={},
            readable_params=["torque_nm"],
            machine=_machine(),
            cost_per_hour=10.0,
            value_add_pct=1.0,
        ),
        StationSpec(
            id="ST-03",
            name="Mid",
            zone=Zone.PAINT,
            sequence_index=2,
            sensors=[_sensor("ST-03-SEN-1", SensorKind.THERMAL)],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            is_inspection_station="ST-03" in inspection_ids,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=_baseline(["ST-03-SEN-1"]),
            machine=_machine(),
            cost_per_hour=10.0,
            value_add_pct=1.0,
        ),
        StationSpec(
            id="ST-04",
            name="Inspection A",
            zone=Zone.FINAL,
            sequence_index=3,
            sensors=[_sensor("ST-04-SEN-1", SensorKind.RPM)],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            is_inspection_station="ST-04" in inspection_ids,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=_baseline(["ST-04-SEN-1"]),
            machine=_machine(),
            cost_per_hour=10.0,
            value_add_pct=1.0,
        ),
        StationSpec(
            id="ST-05",
            name="Inspection B",
            zone=Zone.FINAL,
            sequence_index=4,
            sensors=[_sensor("ST-05-SEN-1", SensorKind.RPM)],
            acquisition_mode=AcquisitionMode.INSTRUMENTED,
            is_inspection_station="ST-05" in inspection_ids,
            cycle_time_nominal_s=10.0,
            commissioning_baseline=_baseline(["ST-05-SEN-1"]),
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


def base_config(**overrides) -> RunConfig:
    defaults = dict(
        run_id="test-run",
        random_seed=42,
        num_cars=20,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[],
        operator_shift_schedule=[],
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


# --- generators.py -----------------------------------------------------------


def test_wear_z_resets_at_maintenance():
    machine = _machine(interval_days=100, shape="linear")
    late = wear_z(machine, elapsed_days=90.0)
    reset = wear_z(machine, elapsed_days=0.0)
    assert reset < late
    assert reset == pytest.approx(0.0, abs=1e-9)


def test_elapsed_days_since_maintenance_uses_latest_in_run_event():
    machine = _machine()
    sim_time = datetime(2024, 6, 1)
    events = [datetime(2024, 5, 1), datetime(2024, 5, 20)]
    elapsed = elapsed_days_since_maintenance(machine, sim_time, events)
    assert elapsed == pytest.approx(12.0, abs=1e-6)


def _two_operator_profiles() -> dict[str, OperatorProfile]:
    return {
        "A": OperatorProfile(operator_id="A", bias=0.0, std=0.3),
        "B": OperatorProfile(operator_id="B", bias=5.0, std=0.3),
    }


def test_operator_bias_unflagged_handover_is_a_hard_step():
    profiles = _two_operator_profiles()
    schedule = [
        ShiftAssignment(station_id="ST-02", operator_id="A", start_car_index=0, end_car_index=9),
        ShiftAssignment(
            station_id="ST-02",
            operator_id="B",
            start_car_index=10,
            end_car_index=19,
            handover_flagged=False,
        ),
    ]
    bias, _ = operator_bias_for_car(schedule, profiles, "ST-02", 10)
    assert bias == pytest.approx(5.0)


def test_operator_bias_flagged_handover_is_dampened():
    profiles = _two_operator_profiles()
    schedule = [
        ShiftAssignment(station_id="ST-02", operator_id="A", start_car_index=0, end_car_index=9),
        ShiftAssignment(
            station_id="ST-02",
            operator_id="B",
            start_car_index=10,
            end_car_index=19,
            handover_flagged=True,
        ),
    ]
    bias, _ = operator_bias_for_car(schedule, profiles, "ST-02", 10)
    assert 0.0 < bias < 5.0
    assert bias == pytest.approx(1.5)  # 0.0 + 0.3*(5.0-0.0)


# --- simulate_run / reproducibility ------------------------------------------


def test_same_seed_produces_identical_tick_sequence():
    line = make_test_line()
    config = base_config()

    result_a = simulate_run(line, config)
    result_b = simulate_run(line, config)

    rows_a = [r.__dict__ for r in result_a.telemetry_rows]
    rows_b = [r.__dict__ for r in result_b.telemetry_rows]
    assert rows_a == rows_b
    assert result_a.car_journeys == result_b.car_journeys


def test_environment_excursion_outside_envelope_is_flagged_invalid():
    line = make_test_line()
    config = base_config(
        environment_excursions=[
            EnvironmentExcursion(
                id="e1", zone=Zone.PAINT, start_car_index=0, end_car_index=5, temp_c=40.0
            )
        ]
    )
    artifacts = generate_run(line, config, output_root=_tmp_output())
    import json

    gt = json.loads(artifacts.ground_truth_path.read_text())
    assert gt["environment_valid"] is False
    assert gt["invalid_windows"] == [{"start_car_index": 0, "end_car_index": 5, "temp_c": 40.0}]


def test_material_quality_raises_organic_defect_rate():
    line = make_test_line()
    low_rate = simulate_run(line, base_config(background_defect_rate=0.0))
    high_rate = simulate_run(line, base_config(background_defect_rate=0.5, random_seed=7))
    assert len(low_rate.origin_flags) == 0
    assert len(high_rate.origin_flags) > 0


# --- the latency test: the actual point of the module ------------------------


def test_latent_defect_is_absent_from_inspection_until_the_configured_surfacing_point():
    line = make_test_line(inspection_ids={"ST-04", "ST-05"})
    config = base_config(
        num_cars=5,
        defect_seeds=[
            DefectSeed(
                id="seed-1",
                mechanism=DefectMechanism.TORQUE_DRIFT,
                station_id="ST-01",
                onset_car_index=0,
                duration_cars=5,
                severity=10.0,
                surfaces_after_inspections=2,
            )
        ],
    )
    result = simulate_run(line, config)
    _, inspection_rows = build_ground_truth_and_inspections(
        run_id=config.run_id,
        seed=config.random_seed,
        line=line,
        origin_flags=result.origin_flags,
        car_journeys=result.car_journeys,
        surfaces_after_inspections=result.surfaces_after_inspections,
        invalid_windows=[],
    )
    by_car = {(r.car_id, r.station_id): r for r in inspection_rows}
    car_id = "CAR-00000"
    # A naive reader scanning inspection.csv row by row for this car must see a
    # clean PASS at the first inspection point (ST-04) -- the defect is real and
    # present in ST-01's telemetry, but hasn't surfaced yet.
    assert by_car[(car_id, "ST-04")].result == "pass"
    # It only surfaces at the second configured inspection occurrence, ST-05.
    assert by_car[(car_id, "ST-05")].result == "fail"
    assert by_car[(car_id, "ST-05")].defect_type == "torque_drift"


# --- buffer/blockage derivation ----------------------------------------------


def test_blockage_detected_when_transit_overlap_exceeds_capacity():
    base = datetime(2024, 1, 1)
    intervals = [(base, base.replace(second=30)) for _ in range(5)]  # 5 fully overlapping
    events = _derive_buffer_events("ST-02", intervals, capacity=3)
    assert any(e.event_type == "blockage_start" for e in events)
    assert any(e.event_type == "blockage_end" for e in events)


# --- CSV schema / row-count sanity -------------------------------------------


def test_generate_run_writes_expected_csv_schemas(tmp_path):
    line = make_test_line()
    config = base_config()
    artifacts = generate_run(line, config, output_root=tmp_path)

    telemetry = pd.read_csv(artifacts.telemetry_path)
    assert list(telemetry.columns) == [
        "timestamp", "car_id", "station_id", "sensor_id", "quantity", "value", "acquisition_mode",
    ]

    events = pd.read_csv(artifacts.events_path)
    assert list(events.columns) == ["timestamp", "event_type", "car_id", "station_id", "detail"]

    inspection = pd.read_csv(artifacts.inspection_path)
    expected_cols = ["timestamp", "car_id", "station_id", "result", "defect_type"]
    assert list(inspection.columns) == expected_cols
    assert len(inspection) == config.num_cars * 2  # 2 inspection stations in make_test_line


def _tmp_output():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())
