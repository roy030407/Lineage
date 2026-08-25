"""Assembles the ground-truth answer key from raw defect origin flags, and
produces the inspection.csv pass/fail rows consistent with it. Writes
ground_truth.json with disciplined, reproducible formatting -- this file is
what every later prompt's Predict/Trace correctness gets graded against."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lineage.config.specs import LineSpec
from lineage.datagen.models import DefectMechanism, GroundTruth, GroundTruthDefect, InvalidWindow
from lineage.datagen.scenarios import OriginFlag


@dataclass(frozen=True)
class InspectionRow:
    timestamp: datetime
    car_id: str
    station_id: str
    result: str  # "pass" | "fail"
    defect_type: str  # "" when pass


def inspection_station_ids_in_order(line: LineSpec) -> list[str]:
    return [s.id for s in line.stations if s.is_inspection_station]


def _nth_inspection_downstream(line: LineSpec, origin_station_id: str, n: int) -> str | None:
    origin_index = next(i for i, s in enumerate(line.stations) if s.id == origin_station_id)
    downstream_inspections = [
        s.id for s in line.stations[origin_index + 1 :] if s.is_inspection_station
    ]
    if n > len(downstream_inspections):
        return None
    return downstream_inspections[n - 1]


def _group_origin_flags(
    origin_flags: list[OriginFlag],
) -> list[tuple[str, DefectMechanism, list[OriginFlag]]]:
    """Groups origin flags into contiguous car-index runs per (station, mechanism).

    Two sensors at the same station can independently cross threshold for the
    same car and mechanism (e.g. both catching the same material-quality spike);
    that's one defect event, not two, so duplicates by (car_index, station_id,
    mechanism) collapse to a single flag before grouping into runs.
    """
    deduped: dict[tuple[int, str, DefectMechanism], OriginFlag] = {}
    for flag in origin_flags:
        deduped.setdefault((flag.car_index, flag.station_id, flag.mechanism), flag)

    by_key: dict[tuple[str, DefectMechanism], list[OriginFlag]] = {}
    ordered = sorted(deduped.values(), key=lambda f: (f.station_id, f.mechanism.value, f.car_index))
    for flag in ordered:
        by_key.setdefault((flag.station_id, flag.mechanism), []).append(flag)

    groups: list[tuple[str, DefectMechanism, list[OriginFlag]]] = []
    for (station_id, mechanism), flags in by_key.items():
        run: list[OriginFlag] = []
        for flag in flags:
            if run and flag.car_index != run[-1].car_index + 1:
                groups.append((station_id, mechanism, run))
                run = []
            run.append(flag)
        if run:
            groups.append((station_id, mechanism, run))
    return groups


def build_ground_truth_and_inspections(
    *,
    run_id: str,
    seed: int,
    line: LineSpec,
    origin_flags: list[OriginFlag],
    car_journeys: dict[str, dict[str, datetime]],
    surfaces_after_inspections: dict[tuple[str, DefectMechanism], int],
    invalid_windows: list[InvalidWindow],
) -> tuple[GroundTruth, list[InspectionRow]]:
    """`car_journeys` maps car_id -> {station_id: entry_timestamp}, covering every
    station every car passes (no station-skipping is modeled). `surfaces_after_inspections`
    gives the configured delay for a given (origin_station_id, mechanism) pair;
    entries absent from it (organic wear/material defects) default to 1."""
    inspection_station_ids = inspection_station_ids_in_order(line)
    all_car_ids = sorted(car_journeys.keys())

    groups = _group_origin_flags(origin_flags)

    defects: list[GroundTruthDefect] = []
    fail_lookup: dict[tuple[str, str], DefectMechanism] = {}

    for station_id, mechanism, flags in groups:
        n = surfaces_after_inspections.get((station_id, mechanism), 1)
        detection_station_id = _nth_inspection_downstream(line, station_id, n)
        cars_exposed = [f.car_id for f in flags]
        first_flag = flags[0]

        detected = detection_station_id is not None
        detected_at_timestamp = None
        if detected:
            detected_at_timestamp = car_journeys[first_flag.car_id][detection_station_id]
            for car_id in cars_exposed:
                fail_lookup[(car_id, detection_station_id)] = mechanism

        defects.append(
            GroundTruthDefect(
                defect_id=f"{mechanism.value}-{station_id}-{first_flag.car_index:05d}",
                mechanism=mechanism,
                origin_station_id=station_id,
                onset_timestamp=first_flag.timestamp,
                cars_exposed=cars_exposed,
                detected=detected,
                detected_at_station_id=detection_station_id if detected else None,
                detected_at_timestamp=detected_at_timestamp,
            )
        )

    defects.sort(key=lambda d: (d.onset_timestamp, d.origin_station_id))

    inspection_rows: list[InspectionRow] = []
    for car_id in all_car_ids:
        for station_id in inspection_station_ids:
            timestamp = car_journeys[car_id][station_id]
            mechanism = fail_lookup.get((car_id, station_id))
            inspection_rows.append(
                InspectionRow(
                    timestamp=timestamp,
                    car_id=car_id,
                    station_id=station_id,
                    result="fail" if mechanism else "pass",
                    defect_type=mechanism.value if mechanism else "",
                )
            )

    ground_truth = GroundTruth(
        run_id=run_id,
        seed=seed,
        environment_valid=len(invalid_windows) == 0,
        invalid_windows=invalid_windows,
        defects=defects,
    )
    return ground_truth, inspection_rows


def write_ground_truth_json(ground_truth: GroundTruth, path: Path) -> None:
    data = ground_truth.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
