"""Populates a GenealogyStore from a generated run's CSVs -- the bridge between
datagen's static output and twin's live object history. Reusable by predict's
feature builder now, and trace/ later."""

import json
from pathlib import Path

import pandas as pd

from lineage.config.specs import LineSpec
from lineage.datagen.generators import ambient_temp_c, elapsed_days_since_maintenance, wear_z
from lineage.datagen.models import RunConfig
from lineage.twin.car import AmbientConditions, Reading, StationVisit
from lineage.twin.genealogy import GenealogyStore


def _car_index(car_id: str) -> int:
    return int(car_id.split("-")[1])


def from_generated_run(line: LineSpec, run_dir: Path, config: RunConfig) -> GenealogyStore:
    """Ambient temperature isn't itself a CSV column (datagen only used it
    internally), so it's reconstructed here from the same RunConfig used to
    generate the run -- the caller must supply the matching config."""
    telemetry = pd.read_csv(run_dir / "telemetry.csv", parse_dates=["timestamp"])
    events = pd.read_csv(run_dir / "events.csv", parse_dates=["timestamp"])

    store = GenealogyStore()
    station_by_id = {s.id: s for s in line.stations}

    entries = events[events.event_type == "car_entry"]
    exits = events[events.event_type == "car_exit"]
    shift_changes = events[events.event_type == "shift_change"]
    maintenance = events[events.event_type == "maintenance"]

    exit_by_key = {
        (r.car_id, r.station_id): r.timestamp.to_pydatetime() for r in exits.itertuples()
    }

    telemetry_by_key: dict[tuple[str, str], list] = {}
    for key, group in telemetry.groupby(["car_id", "station_id"]):
        telemetry_by_key[key] = list(group.itertuples())

    shift_changes_by_station: dict[str, list] = {}
    for row in shift_changes.itertuples():
        shift_changes_by_station.setdefault(row.station_id, []).append(
            (row.timestamp.to_pydatetime(), row.detail)
        )
    for rows in shift_changes_by_station.values():
        rows.sort(key=lambda r: r[0])

    maintenance_by_station: dict[str, list] = {}
    for row in maintenance.itertuples():
        maintenance_by_station.setdefault(row.station_id, []).append(row.timestamp.to_pydatetime())

    entries_by_car: dict[str, list] = {}
    for row in entries.itertuples():
        entries_by_car.setdefault(row.car_id, []).append(row)

    for car_id, car_entries in entries_by_car.items():
        car_entries.sort(key=lambda r: r.timestamp)
        car_index = _car_index(car_id)
        first_entry_time = car_entries[0].timestamp.to_pydatetime()
        store.register_car(car_id, model_variant="standard", entry_timestamp=first_entry_time)

        for entry_row in car_entries:
            station_id = entry_row.station_id
            station = station_by_id[station_id]
            entry_time = entry_row.timestamp.to_pydatetime()
            exit_time = exit_by_key.get((car_id, station_id), entry_time)

            reading_rows = telemetry_by_key.get((car_id, station_id), [])
            reading_objs = [
                Reading(
                    sensor_id=r.sensor_id,
                    quantity=r.quantity,
                    value=float(r.value),
                    acquisition_mode=r.acquisition_mode,
                )
                for r in reading_rows
            ]

            operator_id = None
            handover_flagged = None
            candidates = [
                detail
                for ts, detail in shift_changes_by_station.get(station_id, [])
                if ts <= entry_time
            ]
            if candidates:
                operator_id = json.loads(candidates[-1]).get("operator_id")
            exact_match = next(
                (
                    detail
                    for ts, detail in shift_changes_by_station.get(station_id, [])
                    if ts == entry_time
                ),
                None,
            )
            if exact_match is not None:
                handover_flagged = json.loads(exact_match).get("handover_flagged")

            elapsed_days = elapsed_days_since_maintenance(
                station.machine, entry_time, maintenance_by_station.get(station_id, [])
            )
            wear_state = wear_z(station.machine, elapsed_days)
            ambient_c = ambient_temp_c(
                config.baseline_temp_c, config.environment_excursions, car_index, station.zone
            )

            visit = StationVisit(
                station_id=station_id,
                entry_time=entry_time,
                exit_time=exit_time,
                readings=reading_objs,
                operator_id=operator_id,
                handover_flagged=handover_flagged,
                machine_wear_state=wear_state,
                ambient_conditions=AmbientConditions(temp_c=ambient_c),
            )
            store.record_visit(car_id, visit)

    return store
