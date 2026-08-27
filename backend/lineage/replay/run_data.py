"""Loads a generated run's CSVs and answers "what was the line's state as of
this simulated timestamp" queries -- the bridge between datagen's static
output files and ReplayEngine's live-feeling tick stream."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from lineage.config.specs import StationSpec
from lineage.replay.models import LatestReading, SensorHealth


class RunData:
    def __init__(self, run_id: str, run_dir: Path, sensor_stale_after_s: float = 60.0) -> None:
        self.run_id = run_id
        self.sensor_stale_after_s = sensor_stale_after_s

        self._telemetry = pd.read_csv(run_dir / "telemetry.csv", parse_dates=["timestamp"])
        self._telemetry.sort_values("timestamp", inplace=True)

        self._events = pd.read_csv(run_dir / "events.csv", parse_dates=["timestamp"])
        self._events.sort_values("timestamp", inplace=True)

        self.start_time: datetime = self._telemetry.timestamp.min().to_pydatetime()

    def car_at_station_at(self, station_id: str, timestamp: datetime) -> str | None:
        rows = self._events[
            (self._events.station_id == station_id)
            & (self._events.event_type.isin(["car_entry", "car_exit"]))
            & (self._events.timestamp <= timestamp)
        ]
        if rows.empty:
            return None
        last = rows.iloc[-1]
        return str(last.car_id) if last.event_type == "car_entry" else None

    def buffer_depth_at(self, station_id: str, timestamp: datetime) -> int:
        rows = self._events[
            (self._events.station_id == station_id)
            & (self._events.event_type == "buffer_depth")
            & (self._events.timestamp <= timestamp)
        ]
        if rows.empty:
            return 0
        detail = json.loads(rows.iloc[-1].detail)
        return int(detail["depth"])

    def sensor_is_reporting(self, station: StationSpec, timestamp: datetime) -> SensorHealth:
        """Distinguishes three states: NOT_APPLICABLE (no sensors at all),
        NOT_YET_REPORTING (has sensors, but no telemetry row exists yet
        before `timestamp` -- simulated time simply hasn't reached this
        station, not a fault), and GREEN/RED (has reported before; RED means
        its latest reading is older than sensor_stale_after_s, a real
        "stopped reporting" fault)."""
        if not station.sensors:
            return SensorHealth.NOT_APPLICABLE
        rows = self._telemetry[
            (self._telemetry.station_id == station.id) & (self._telemetry.timestamp <= timestamp)
        ]
        if rows.empty:
            return SensorHealth.NOT_YET_REPORTING
        last_ts = rows.iloc[-1].timestamp.to_pydatetime()
        is_fresh = (timestamp - last_ts) <= timedelta(seconds=self.sensor_stale_after_s)
        return SensorHealth.GREEN if is_fresh else SensorHealth.RED

    def latest_readings_at(self, station: StationSpec, timestamp: datetime) -> list[LatestReading]:
        """The most recent reading for each of this station's sensors (or
        manual quantities) at or before `timestamp` -- one entry per
        sensor_id that has reported at all so far, none for one that
        hasn't (never a fabricated placeholder value)."""
        rows = self._telemetry[
            (self._telemetry.station_id == station.id) & (self._telemetry.timestamp <= timestamp)
        ]
        if rows.empty:
            return []
        latest_per_sensor = rows.sort_values("timestamp").groupby("sensor_id").tail(1)
        return [
            LatestReading(
                sensor_id=row.sensor_id,
                quantity=row.quantity,
                value=float(row.value),
                timestamp=row.timestamp.to_pydatetime(),
            )
            for row in latest_per_sensor.itertuples()
        ]

    def reading_history_at(
        self, station_id: str, quantity: str, up_to: datetime
    ) -> list[tuple[datetime, float, str]]:
        """Every reading of `quantity` at `station_id` at or before `up_to`,
        oldest first, as (timestamp, value, car_id) -- the ordered history
        evaluate_spc needs to score the live control state of a station
        in-progress, not just its latest single reading. `quantity` matches
        either a sensor_id or a manual reading's quantity name, same as
        predict/risk.py's history builder."""
        rows = self._telemetry[
            (self._telemetry.station_id == station_id)
            & (self._telemetry.timestamp <= up_to)
            & ((self._telemetry.sensor_id == quantity) | (self._telemetry.quantity == quantity))
        ].sort_values("timestamp")
        return [
            (row.timestamp.to_pydatetime(), float(row.value), str(row.car_id))
            for row in rows.itertuples()
        ]

    def shift_changes_at(self, station_id: str, up_to: datetime) -> list[tuple[datetime, bool]]:
        """Every shift-change event at `station_id` at or before `up_to`,
        oldest first, as (timestamp, handover_flagged) -- what evaluate_spc
        needs to know when a manual station's recalibration window started."""
        rows = self._events[
            (self._events.station_id == station_id)
            & (self._events.event_type == "shift_change")
            & (self._events.timestamp <= up_to)
        ].sort_values("timestamp")
        return [
            (row.timestamp.to_pydatetime(), bool(json.loads(row.detail)["handover_flagged"]))
            for row in rows.itertuples()
        ]

    def machine_is_maintained(self, station: StationSpec, timestamp: datetime) -> bool:
        maintenance_events = self._events[
            (self._events.station_id == station.id)
            & (self._events.event_type == "maintenance")
            & (self._events.timestamp <= timestamp)
        ]
        if not maintenance_events.empty:
            last_maintenance = maintenance_events.iloc[-1].timestamp.to_pydatetime()
        else:
            last_maintenance = datetime.combine(
                station.machine.last_maintenance_date, datetime.min.time()
            )
        elapsed_days = (timestamp - last_maintenance).total_seconds() / 86400.0
        return elapsed_days <= station.machine.maintenance_interval_days
