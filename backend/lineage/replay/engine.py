"""TickEngine: advances simulated time and emits per-tick station/sensor frames."""

from datetime import datetime

from lineage.config.specs import LineSpec
from lineage.replay.clock import SimClock
from lineage.replay.models import LineState, MachineHealth, StationState
from lineage.replay.run_data import RunData


class ReplayEngine:
    def __init__(
        self,
        line: LineSpec,
        run_data: RunData,
        start_time: datetime,
        tick_interval_real_s: float = 1.0,
    ) -> None:
        self.line = line
        self.run_data = run_data
        self.clock = SimClock(start_time, tick_interval_real_s=tick_interval_real_s)

    def pause(self) -> None:
        self.clock.pause()

    def resume(self) -> None:
        self.clock.resume()

    def set_step_mode(self) -> None:
        self.clock.set_step_mode()

    def set_speed(self, multiplier: float) -> None:
        self.clock.set_speed(multiplier)

    def seek(self, timestamp: datetime) -> LineState:
        self.clock.seek(timestamp)
        return self.current_state()

    def step(self) -> LineState:
        self.clock.step()
        return self.current_state()

    def tick(self) -> LineState:
        self.clock.auto_tick()
        return self.current_state()

    def current_state(self) -> LineState:
        timestamp = self.clock.current_time
        stations = []
        for station in self.line.stations:
            sensor_health = self.run_data.sensor_is_reporting(station, timestamp)

            machine_health = (
                MachineHealth.GREEN
                if self.run_data.machine_is_maintained(station, timestamp)
                else MachineHealth.RED
            )

            stations.append(
                StationState(
                    station_id=station.id,
                    car_id=self.run_data.car_at_station_at(station.id, timestamp),
                    upstream_buffer_depth=self.run_data.buffer_depth_at(station.id, timestamp),
                    sensor_health=sensor_health,
                    machine_health=machine_health,
                    latest_readings=self.run_data.latest_readings_at(station, timestamp),
                )
            )

        return LineState(
            run_id=self.run_data.run_id,
            timestamp=timestamp,
            speed_multiplier=self.clock.speed_multiplier,
            playback_mode=self.clock.mode,
            stations=stations,
        )
