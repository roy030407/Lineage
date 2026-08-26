"""LineState and the health-signal vocabulary emitted over the WebSocket."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SensorHealth(StrEnum):
    """Whether this station's sensor(s) are currently reporting telemetry --
    NOT whether the readings are accurate. A sensor can be GREEN (reporting
    on schedule) while producing wildly wrong values; accuracy assessment is
    Predict's job and is out of scope for this type."""

    GREEN = "green"
    RED = "red"
    NOT_APPLICABLE = "not_applicable"


class MachineHealth(StrEnum):
    """Whether this station's machine has been maintained within its
    configured interval -- NOT whether it will fail. A recently-maintained
    machine can still fail unexpectedly; failure prediction is Predict's
    job and is out of scope for this type."""

    GREEN = "green"
    RED = "red"


class PlaybackMode(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STEP = "step"


class LatestReading(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    sensor_id: str
    quantity: str
    value: float
    timestamp: datetime


class StationState(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    car_id: str | None
    upstream_buffer_depth: int
    sensor_health: SensorHealth
    machine_health: MachineHealth
    latest_readings: list[LatestReading] = Field(default_factory=list)


class LineState(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    run_id: str
    timestamp: datetime
    speed_multiplier: float
    playback_mode: PlaybackMode
    stations: list[StationState] = Field(default_factory=list)
