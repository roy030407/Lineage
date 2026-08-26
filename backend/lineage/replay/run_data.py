"""Loads a generated run's CSVs and answers "what was the line's state as of
this simulated timestamp" queries -- the bridge between datagen's static
output files and ReplayEngine's live-feeling tick stream."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from lineage.config.specs import StationSpec
from lineage.replay.models import LatestReading


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

    def sensor_is_reporting(self, station: StationSpec, timestamp: datetime) -> bool | None:
        """None if the station has no sensors at all (caller maps that to
        NOT_APPLICABLE); otherwise whether its latest telemetry row is recent
        enough as of `timestamp`."""
        if not station.sensors:
            return None
        rows = self._telemetry[
            (self._telemetry.station_id == station.id) & (self._telemetry.timestamp <= timestamp)
        ]
        if rows.empty:
            return False
        last_ts = rows.iloc[-1].timestamp.to_pydatetime()
        return (timestamp - last_ts) <= timedelta(seconds=self.sensor_stale_after_s)

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
