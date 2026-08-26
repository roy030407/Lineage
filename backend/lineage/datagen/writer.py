"""Drives the per-car, per-station simulation loop and writes telemetry.csv,
events.csv, and the buffer/blockage/shift/maintenance event stream. Ground-truth
assembly and inspection.csv live in ground_truth.py, since they need the full
set of origin flags before inspection results can be decided."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from lineage.config.specs import AcquisitionMode, LineSpec, SensorKind, StationSpec, Zone
from lineage.datagen.generators import (
    ambient_temp_c,
    elapsed_days_since_maintenance,
    material_quality_sequence,
    operator_bias_for_car,
    round_to_step,
)
from lineage.datagen.ground_truth import InspectionRow
from lineage.datagen.models import DefectMechanism, EnvironmentExcursion, RunConfig
from lineage.datagen.scenarios import OriginFlag, compute_reading


@dataclass(frozen=True)
class TelemetryRow:
    timestamp: datetime
    car_id: str
    station_id: str
    sensor_id: str
    quantity: str
    value: float
    acquisition_mode: str


@dataclass(frozen=True)
class EventRow:
    timestamp: datetime
    event_type: str
    car_id: str
    station_id: str
    detail: dict


@dataclass(frozen=True)
class SimulationResult:
    telemetry_rows: list[TelemetryRow]
    events_rows: list[EventRow]
    origin_flags: list[OriginFlag]
    car_journeys: dict[str, dict[str, datetime]]
    surfaces_after_inspections: dict[tuple[str, DefectMechanism], int]


def _active_excursion(
    excursions: list[EnvironmentExcursion], car_index: int, zone: Zone
) -> EnvironmentExcursion | None:
    return next(
        (
            e
            for e in excursions
            if e.zone == zone and e.start_car_index <= car_index <= e.end_car_index
        ),
        None,
    )


def simulate_run(line: LineSpec, config: RunConfig) -> SimulationResult:
    rng = np.random.default_rng(config.random_seed)
    stations = line.stations
    takt_time_s = max(s.cycle_time_nominal_s for s in stations)
    material_quality = material_quality_sequence(config.num_cars, rng)
    operator_profiles = {p.operator_id: p for p in config.operator_profiles}
    segment_distance = {
        (s.from_station_id, s.to_station_id): s.distance_m for s in line.layout.segments
    }
    maintenance_events = {s.id: config.maintenance_events.get(s.id, []) for s in stations}

    telemetry_rows: list[TelemetryRow] = []
    events_rows: list[EventRow] = []
    origin_flags: list[OriginFlag] = []
    car_journeys: dict[str, dict[str, datetime]] = {}
    surfaces_after_inspections: dict[tuple[str, DefectMechanism], int] = {
        (seed.station_id, seed.mechanism): seed.surfaces_after_inspections
        for seed in config.defect_seeds
    }
    emitted_shift_changes: set[tuple[str, int]] = set()
    transit_intervals: dict[str, list[tuple[datetime, datetime]]] = {s.id: [] for s in stations}

    for i in range(config.num_cars):
        car_id = f"CAR-{i:05d}"
        car_journeys[car_id] = {}
        entry_time = config.sim_start_time + timedelta(seconds=i * takt_time_s)

        for idx, station in enumerate(stations):
            car_journeys[car_id][station.id] = entry_time
            ambient_c = ambient_temp_c(
                config.baseline_temp_c, config.environment_excursions, i, station.zone
            )
            events_rows.append(EventRow(entry_time, "car_entry", car_id, station.id, {}))

            assignment = next(
                (
                    a
                    for a in config.operator_shift_schedule
                    if a.station_id == station.id
                    and a.start_car_index <= i <= a.end_car_index
                    and a.start_car_index == i
                ),
                None,
            )
            if assignment is not None:
                key = (station.id, assignment.start_car_index)
                if key not in emitted_shift_changes:
                    emitted_shift_changes.add(key)
                    events_rows.append(
                        EventRow(
                            entry_time,
                            "shift_change",
                            "",
                            station.id,
                            {
                                "operator_id": assignment.operator_id,
                                "handover_flagged": assignment.handover_flagged,
                            },
                        )
                    )

            machine_elapsed_days = elapsed_days_since_maintenance(
                station.machine, entry_time, maintenance_events[station.id]
            )
            seed_component = seed_component_for(config, station.id, i, DefectMechanism.TORQUE_DRIFT)

            if station.acquisition_mode == AcquisitionMode.MANUAL:
                _simulate_manual_station(
                    config=config,
                    line=line,
                    station=station,
                    car_id=car_id,
                    car_index=i,
                    timestamp=entry_time,
                    machine_elapsed_days=machine_elapsed_days,
                    ambient_c=ambient_c,
                    material_quality=material_quality[i],
                    seed_component=seed_component,
                    operator_profiles=operator_profiles,
                    rng=rng,
                    telemetry_rows=telemetry_rows,
                    origin_flags=origin_flags,
                    surfaces_after_inspections=surfaces_after_inspections,
                )
            else:
                _simulate_instrumented_station(
                    config=config,
                    line=line,
                    station=station,
                    car_id=car_id,
                    car_index=i,
                    timestamp=entry_time,
                    machine_elapsed_days=machine_elapsed_days,
                    ambient_c=ambient_c,
                    material_quality=material_quality[i],
                    seed_component=seed_component,
                    rng=rng,
                    telemetry_rows=telemetry_rows,
                    origin_flags=origin_flags,
                    surfaces_after_inspections=surfaces_after_inspections,
                )

            cycle_noise = float(rng.normal(0.0, station.cycle_time_nominal_s * 0.02))
            exit_time = entry_time + timedelta(seconds=station.cycle_time_nominal_s + cycle_noise)
            events_rows.append(EventRow(exit_time, "car_exit", car_id, station.id, {}))

            if idx + 1 < len(stations):
                next_station = stations[idx + 1]
                distance = segment_distance[(station.id, next_station.id)]
                transit_time_s = distance / config.conveyor_speed_mps
                next_entry_time = exit_time + timedelta(seconds=transit_time_s)
                transit_intervals[next_station.id].append((exit_time, next_entry_time))
                entry_time = next_entry_time

    for station in stations:
        events_rows.extend(
            _derive_buffer_events(station.id, transit_intervals[station.id], config.buffer_capacity)
        )

    return SimulationResult(
        telemetry_rows=telemetry_rows,
        events_rows=sorted(events_rows, key=lambda e: e.timestamp),
        origin_flags=origin_flags,
        car_journeys=car_journeys,
        surfaces_after_inspections=surfaces_after_inspections,
    )


def seed_component_for(
    config: RunConfig, station_id: str, car_index: int, mechanism: DefectMechanism
) -> float:
    total = 0.0
    for seed in config.defect_seeds:
        if (
            seed.mechanism == mechanism
            and seed.station_id == station_id
            and seed.onset_car_index <= car_index < seed.onset_car_index + seed.duration_cars
        ):
            total += seed.severity
    return total


def _simulate_instrumented_station(
    *,
    config: RunConfig,
    line: LineSpec,
    station: StationSpec,
    car_id: str,
    car_index: int,
    timestamp: datetime,
    machine_elapsed_days: float,
    ambient_c: float,
    material_quality: float,
    seed_component: float,
    rng: np.random.Generator,
    telemetry_rows: list[TelemetryRow],
    origin_flags: list[OriginFlag],
    surfaces_after_inspections: dict[tuple[str, DefectMechanism], int],
) -> None:
    baseline = station.commissioning_baseline.loaded
    for sensor in station.sensors:
        mean = baseline.mean[sensor.id]
        std = baseline.std[sensor.id]
        # A torque-drift seed perturbs the torque reading specifically, not every
        # sensor that happens to share its station -- otherwise a station's
        # unrelated thermal/vibration sensor would spuriously "catch" the same
        # seeded defect and fragment the ground-truth grouping.
        sensor_seed_component = seed_component if sensor.kind == SensorKind.TORQUE else 0.0
        reading = compute_reading(
            config=config,
            machine=station.machine,
            sensor_kind=sensor.kind,
            baseline_mean=mean,
            baseline_std=std,
            noise_std=std,
            machine_elapsed_days=machine_elapsed_days,
            ambient_c=ambient_c,
            envelope_min_c=line.environment_envelope.temp_min_c,
            envelope_max_c=line.environment_envelope.temp_max_c,
            material_quality=material_quality,
            seed_component=sensor_seed_component,
            operator_bias=0.0,
            rng=rng,
        )
        telemetry_rows.append(
            TelemetryRow(
                timestamp=timestamp,
                car_id=car_id,
                station_id=station.id,
                sensor_id=sensor.id,
                quantity=sensor.kind.value,
                value=round(reading.value, 3),
                acquisition_mode=station.acquisition_mode.value,
            )
        )
        if reading.mechanism is not None:
            origin_flags.append(
                OriginFlag(car_index, car_id, station.id, timestamp, reading.mechanism)
            )
            if reading.mechanism is DefectMechanism.ENVIRONMENTAL_EXCURSION:
                excursion = _active_excursion(
                    config.environment_excursions, car_index, station.zone
                )
                if excursion is not None:
                    key = (station.id, reading.mechanism)
                    surfaces_after_inspections.setdefault(key, excursion.surfaces_after_inspections)


def _simulate_manual_station(
    *,
    config: RunConfig,
    line: LineSpec,
    station: StationSpec,
    car_id: str,
    car_index: int,
    timestamp: datetime,
    machine_elapsed_days: float,
    ambient_c: float,
    material_quality: float,
    seed_component: float,
    operator_profiles: dict,
    rng: np.random.Generator,
    telemetry_rows: list[TelemetryRow],
    origin_flags: list[OriginFlag],
    surfaces_after_inspections: dict[tuple[str, DefectMechanism], int],
) -> None:
    quantity = station.readable_params[0]
    baseline = station.commissioning_baseline.loaded
    mean = baseline.mean[quantity]
    std = baseline.std[quantity]

    operator_result = operator_bias_for_car(
        config.operator_shift_schedule, operator_profiles, station.id, car_index
    )
    bias, op_std = operator_result if operator_result is not None else (0.0, std)

    report_roll = float(rng.uniform(0.0, 1.0))
    reading = compute_reading(
        config=config,
        machine=station.machine,
        sensor_kind=None,
        baseline_mean=mean,
        baseline_std=std,
        noise_std=op_std,
        machine_elapsed_days=machine_elapsed_days,
        ambient_c=ambient_c,
        envelope_min_c=line.environment_envelope.temp_min_c,
        envelope_max_c=line.environment_envelope.temp_max_c,
        material_quality=material_quality,
        seed_component=seed_component,
        operator_bias=bias,
        rng=rng,
    )
    if report_roll < config.manual_report_probability:
        telemetry_rows.append(
            TelemetryRow(
                timestamp=timestamp,
                car_id=car_id,
                station_id=station.id,
                sensor_id=f"{station.id}-MANUAL-{quantity}",
                quantity=quantity,
                value=round_to_step(reading.value, quantity),
                acquisition_mode=station.acquisition_mode.value,
            )
        )
    if reading.mechanism is not None:
        origin_flags.append(OriginFlag(car_index, car_id, station.id, timestamp, reading.mechanism))


def _derive_buffer_events(
    station_id: str, intervals: list[tuple[datetime, datetime]], capacity: int
) -> list[EventRow]:
    """Sweeps a gap's (exit-from-upstream, entry-to-this-station) intervals to
    derive buffer depth over time, and flags blockage windows where depth
    exceeds capacity."""
    if not intervals:
        return []
    boundaries: list[tuple[datetime, int]] = []
    for start, end in intervals:
        boundaries.append((start, 1))
        boundaries.append((end, -1))
    boundaries.sort(key=lambda b: (b[0], -b[1]))

    events: list[EventRow] = []
    depth = 0
    blocked = False
    for timestamp, delta in boundaries:
        depth += delta
        events.append(EventRow(timestamp, "buffer_depth", "", station_id, {"depth": depth}))
        if depth > capacity and not blocked:
            blocked = True
            events.append(EventRow(timestamp, "blockage_start", "", station_id, {}))
        elif depth <= capacity and blocked:
            blocked = False
            events.append(EventRow(timestamp, "blockage_end", "", station_id, {}))
    return events


TELEMETRY_COLUMNS = [
    "timestamp",
    "car_id",
    "station_id",
    "sensor_id",
    "quantity",
    "value",
    "acquisition_mode",
]
EVENTS_COLUMNS = ["timestamp", "event_type", "car_id", "station_id", "detail"]
INSPECTION_COLUMNS = ["timestamp", "car_id", "station_id", "result", "defect_type"]


def write_telemetry_csv(rows: list[TelemetryRow], path: Path) -> None:
    df = pd.DataFrame([r.__dict__ for r in rows], columns=TELEMETRY_COLUMNS)
    df = df.sort_values(["timestamp", "car_id", "station_id", "sensor_id"]).reset_index(drop=True)
    df.to_csv(path, index=False)


def write_events_csv(rows: list[EventRow], path: Path) -> None:
    records = [
        {
            **{k: v for k, v in r.__dict__.items() if k != "detail"},
            "detail": json.dumps(r.detail, sort_keys=True),
        }
        for r in rows
    ]
    df = pd.DataFrame(records, columns=EVENTS_COLUMNS)
    sort_cols = ["timestamp", "event_type", "station_id"]
    df = df.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    df.to_csv(path, index=False)


def write_inspection_csv(rows: list[InspectionRow], path: Path) -> None:
    df = pd.DataFrame([r.__dict__ for r in rows], columns=INSPECTION_COLUMNS)
    df = df.sort_values(["timestamp", "car_id", "station_id"]).reset_index(drop=True)
    df.to_csv(path, index=False)
