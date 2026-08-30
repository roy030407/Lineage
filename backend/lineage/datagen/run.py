"""Top-level orchestrator: generate_run() ties simulation, ground-truth
assembly, and CSV/JSON writing together into a run directory."""

import warnings
from pathlib import Path

from lineage.config.specs import LineSpec
from lineage.datagen.ground_truth import build_ground_truth_and_inspections, write_ground_truth_json
from lineage.datagen.models import InvalidWindow, RunArtifacts, RunConfig
from lineage.datagen.writer import (
    simulate_run,
    write_events_csv,
    write_inspection_csv,
    write_telemetry_csv,
)


def generate_run(line: LineSpec, config: RunConfig, output_root: Path) -> RunArtifacts:
    # A defect seed aimed at a station this line doesn't have silently
    # contributes nothing to any reading -- a real trap when the default
    # run config (which names specific example_42 stations) is used against
    # a builder-made line. Loud, not fatal: the run still generates, but
    # nobody should discover the missing scenario only at demo time.
    line_station_ids = {station.id for station in line.stations}
    for seed in config.defect_seeds:
        if seed.station_id not in line_station_ids:
            warnings.warn(
                f"defect seed {seed.mechanism.value!r} targets station "
                f"{seed.station_id!r}, which is not on line {line.plant_name!r} -- "
                "the seeded scenario will not appear in this run",
                stacklevel=2,
            )

    result = simulate_run(line, config)

    invalid_windows = [
        InvalidWindow(
            start_car_index=e.start_car_index, end_car_index=e.end_car_index, temp_c=e.temp_c
        )
        for e in config.environment_excursions
        if e.temp_c > line.environment_envelope.temp_max_c
        or e.temp_c < line.environment_envelope.temp_min_c
    ]

    ground_truth, inspection_rows = build_ground_truth_and_inspections(
        run_id=config.run_id,
        seed=config.random_seed,
        line=line,
        origin_flags=result.origin_flags,
        car_journeys=result.car_journeys,
        surfaces_after_inspections=result.surfaces_after_inspections,
        invalid_windows=invalid_windows,
    )

    output_dir = output_root / config.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    telemetry_path = output_dir / "telemetry.csv"
    events_path = output_dir / "events.csv"
    inspection_path = output_dir / "inspection.csv"
    ground_truth_path = output_dir / "ground_truth.json"
    run_config_path = output_dir / "run_config.json"

    write_telemetry_csv(result.telemetry_rows, telemetry_path)
    write_events_csv(result.events_rows, events_path)
    write_inspection_csv(inspection_rows, inspection_path)
    write_ground_truth_json(ground_truth, ground_truth_path)
    run_config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")

    return RunArtifacts(
        run_id=config.run_id,
        output_dir=output_dir,
        telemetry_path=telemetry_path,
        events_path=events_path,
        inspection_path=inspection_path,
        ground_truth_path=ground_truth_path,
        run_config_path=run_config_path,
        num_cars=config.num_cars,
    )
