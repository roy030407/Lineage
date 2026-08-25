"""Command-line entrypoint for generating synthetic data (used by `make gen`).

Builds the default 400-car run over example_42.yaml with the three named
scenarios: torque drift at ST-06 surfacing at the Final Roll Test, a paint-booth
environmental excursion at ST-25 surfacing at ST-26, and an unflagged
operator-handover shift at manual station ST-02 surfacing at ST-16.
"""

from pathlib import Path

from lineage.config.loader import load_line_spec
from lineage.config.specs import AcquisitionMode, LineSpec, Zone
from lineage.datagen.models import (
    DefectMechanism,
    DefectSeed,
    EnvironmentExcursion,
    OperatorProfile,
    RunConfig,
    ShiftAssignment,
)
from lineage.datagen.run import generate_run

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LINE_PATH = BACKEND_DIR / "data" / "lines" / "example_42.yaml"
DEFAULT_OUTPUT_ROOT = BACKEND_DIR / "data" / "runs"

TORQUE_DRIFT_STATION = "ST-06"
ENVIRONMENT_STATION_HINT = "ST-25"  # the only paint-zone station with a thermal sensor
OPERATOR_SCENARIO_STATION = "ST-02"


def _default_operator_setup(
    line: LineSpec,
) -> tuple[list[OperatorProfile], list[ShiftAssignment]]:
    manual_station_ids = [
        s.id for s in line.stations if s.acquisition_mode == AcquisitionMode.MANUAL
    ]
    profiles: list[OperatorProfile] = []
    schedule: list[ShiftAssignment] = []

    for station_id in manual_station_ids:
        op_a = f"OP-{station_id}-A"
        op_b = f"OP-{station_id}-B"
        if station_id == OPERATOR_SCENARIO_STATION:
            # bias is z-scored against the quantity's baseline std (~0.8 here) for
            # detection purposes, not against the operator's own measurement std --
            # needs to be large enough to robustly dominate an occasional
            # unrelated material-quality spike (z ~= 4.0 +/- 0.5), not just clear
            # the bare 3.0 threshold.
            bias_b, std, flagged = 6.0, 0.3, False
        else:
            bias_b, std, flagged = 0.4, 0.3, True

        profiles.append(OperatorProfile(operator_id=op_a, bias=0.0, std=std))
        profiles.append(OperatorProfile(operator_id=op_b, bias=bias_b, std=std))
        schedule.append(
            ShiftAssignment(
                station_id=station_id,
                operator_id=op_a,
                start_car_index=0,
                end_car_index=199,
                handover_flagged=False,
            )
        )
        schedule.append(
            ShiftAssignment(
                station_id=station_id,
                operator_id=op_b,
                start_car_index=200,
                end_car_index=399,
                handover_flagged=flagged,
            )
        )

    return profiles, schedule


def build_default_run_config(line: LineSpec) -> RunConfig:
    operator_profiles, operator_shift_schedule = _default_operator_setup(line)

    return RunConfig(
        run_id="default_400_car_run",
        random_seed=20240101,
        num_cars=400,
        background_defect_rate=0.0005,
        defect_z_threshold=3.0,
        defect_seeds=[
            DefectSeed(
                id="seed-torque-drift-01",
                mechanism=DefectMechanism.TORQUE_DRIFT,
                station_id=TORQUE_DRIFT_STATION,
                onset_car_index=50,
                duration_cars=30,
                severity=4.0,
                surfaces_after_inspections=3,
            ),
        ],
        environment_excursions=[
            EnvironmentExcursion(
                id="exc-paint-booth-01",
                zone=Zone.PAINT,
                start_car_index=150,
                end_car_index=170,
                temp_c=35.0,
                surfaces_after_inspections=1,
            ),
        ],
        baseline_temp_c=22.0,
        operator_profiles=operator_profiles,
        operator_shift_schedule=operator_shift_schedule,
    )


def main() -> None:
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)
    artifacts = generate_run(line, config, DEFAULT_OUTPUT_ROOT)
    print(f"wrote run {artifacts.run_id} ({artifacts.num_cars} cars) to {artifacts.output_dir}")
    print(f"  telemetry:    {artifacts.telemetry_path}")
    print(f"  events:       {artifacts.events_path}")
    print(f"  inspection:   {artifacts.inspection_path}")
    print(f"  ground_truth: {artifacts.ground_truth_path}")


if __name__ == "__main__":
    main()
