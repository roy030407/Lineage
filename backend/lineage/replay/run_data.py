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
        # The last moment this run has anything real to say. Past it, every
        # per-station query below degrades to "no car, stale sensor", which
        # ReplayEngine must not present as a live line-wide fault. Takes the
        # max across both frames because a run's final car_exit event can
        # land after its final telemetry row.
        self.end_time: datetime = max(
            self._telemetry.timestamp.max().to_pydatetime(),
            self._events.timestamp.max().to_pydatetime(),
        )

        # Every per-station query below used to filter the full, ever-growing
        # telemetry/events frame from scratch -- fine at the scale the
        # original single-station queries ran at, but a real, measured cost
        # once a live view (Floor Supervisor's SPC alarm feed) started asking
        # this per-station question for every station on every poll: ~0.86s
        # across 42 stations against a 2-hour-in 400-car run, unindexed.
        # Grouping once here means each per-station query only filters that
        # station's own, much smaller slice.
        self._empty_telemetry = self._telemetry.iloc[0:0]
        self._telemetry_by_station: dict[str, pd.DataFrame] = dict(
            tuple(self._telemetry.groupby("station_id"))
        )
        self._empty_events = self._events.iloc[0:0]
        self._events_by_station: dict[str, pd.DataFrame] = dict(
            tuple(self._events.groupby("station_id"))
        )

    def _telemetry_for(self, station_id: str) -> pd.DataFrame:
        return self._telemetry_by_station.get(station_id, self._empty_telemetry)

    def _events_for(self, station_id: str) -> pd.DataFrame:
        return self._events_by_station.get(station_id, self._empty_events)

    def car_at_station_at(self, station_id: str, timestamp: datetime) -> str | None:
        events = self._events_for(station_id)
        rows = events[
            events.event_type.isin(["car_entry", "car_exit"]) & (events.timestamp <= timestamp)
        ]
        if rows.empty:
            return None
        last = rows.iloc[-1]
        return str(last.car_id) if last.event_type == "car_entry" else None

    def buffer_depth_at(self, station_id: str, timestamp: datetime) -> int:
        events = self._events_for(station_id)
        rows = events[(events.event_type == "buffer_depth") & (events.timestamp <= timestamp)]
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
        rows = self._telemetry_for(station.id)
        rows = rows[rows.timestamp <= timestamp]
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
        rows = self._telemetry_for(station.id)
        rows = rows[rows.timestamp <= timestamp]
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
        telemetry = self._telemetry_for(station_id)
        rows = telemetry[
            (telemetry.timestamp <= up_to)
            & ((telemetry.sensor_id == quantity) | (telemetry.quantity == quantity))
        ].sort_values("timestamp")
        return [
            (row.timestamp.to_pydatetime(), float(row.value), str(row.car_id))
            for row in rows.itertuples()
        ]

    def shift_changes_at(self, station_id: str, up_to: datetime) -> list[tuple[datetime, bool]]:
        """Every shift-change event at `station_id` at or before `up_to`,
        oldest first, as (timestamp, handover_flagged) -- what evaluate_spc
        needs to know when a manual station's recalibration window started."""
        events = self._events_for(station_id)
        rows = events[
            (events.event_type == "shift_change") & (events.timestamp <= up_to)
        ].sort_values("timestamp")
        return [
            (row.timestamp.to_pydatetime(), bool(json.loads(row.detail)["handover_flagged"]))
            for row in rows.itertuples()
        ]

    def days_since_maintenance_at(self, station: StationSpec, timestamp: datetime) -> float:
        """Days since the most recent maintenance at or before `timestamp` --
        an in-run maintenance event if one has happened, else the station's
        commissioning-time last_maintenance_date. Shared by
        machine_is_maintained (a threshold check) and Plant Manager's
        maintenance-schedule reporting (the actual number)."""
        events = self._events_for(station.id)
        maintenance_events = events[
            (events.event_type == "maintenance") & (events.timestamp <= timestamp)
        ]
        if not maintenance_events.empty:
            last_maintenance = maintenance_events.iloc[-1].timestamp.to_pydatetime()
        else:
            last_maintenance = datetime.combine(
                station.machine.last_maintenance_date, datetime.min.time()
            )
        return (timestamp - last_maintenance).total_seconds() / 86400.0

    def machine_is_maintained(self, station: StationSpec, timestamp: datetime) -> bool:
        elapsed_days = self.days_since_maintenance_at(station, timestamp)
        return elapsed_days <= station.machine.maintenance_interval_days
