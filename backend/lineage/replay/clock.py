"""SimClock: simulated time, real-time or accelerated-multiplier playback."""

from datetime import datetime, timedelta

from lineage.replay.models import PlaybackMode


class SimClock:
    def __init__(
        self,
        start_time: datetime,
        tick_interval_real_s: float = 1.0,
        speed_multiplier: float = 1.0,
    ) -> None:
        self.current_time = start_time
        self.tick_interval_real_s = tick_interval_real_s
        self.speed_multiplier = speed_multiplier
        self.mode = PlaybackMode.PLAYING

    def auto_tick(self) -> None:
        """Called by the background driving loop. Only advances time while
        PLAYING -- a no-op in PAUSED or STEP, which is what makes pausing (and
        not stepping) stop the clock from moving at all."""
        if self.mode != PlaybackMode.PLAYING:
            return
        self.current_time += timedelta(seconds=self.tick_interval_real_s * self.speed_multiplier)

    def step(self) -> None:
        """Advances by exactly one fixed increment regardless of mode. This is
        the explicit control STEP mode relies on, since STEP mode's auto_tick
        is otherwise a no-op."""
        self.current_time += timedelta(seconds=self.tick_interval_real_s)

    def pause(self) -> None:
        self.mode = PlaybackMode.PAUSED

    def resume(self) -> None:
        self.mode = PlaybackMode.PLAYING

    def set_step_mode(self) -> None:
        self.mode = PlaybackMode.STEP

    def set_speed(self, multiplier: float) -> None:
        if multiplier <= 0:
            raise ValueError(f"speed multiplier must be > 0, got {multiplier}")
        self.speed_multiplier = multiplier

    def seek(self, timestamp: datetime) -> None:
        self.current_time = timestamp
