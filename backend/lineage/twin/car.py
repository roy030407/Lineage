"""Car twin: per-station visit history (entry/exit, readings, ambient).

model_variant exists on the twin but every generated car is currently
"standard" (see twin/ingest.py) -- datagen does not yet vary trim/spec,
so no downstream logic keys off it."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Reading(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    sensor_id: str
    quantity: str
    value: float
    acquisition_mode: str


class AmbientConditions(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    temp_c: float
    humidity_pct: float | None = None


class StationVisit(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    entry_time: datetime
    exit_time: datetime
    readings: list[Reading] = Field(default_factory=list)
    operator_id: str | None = None
    handover_flagged: bool | None = None
    """Set only on the visit that coincides with a shift-change event at this
    station; None on every other visit. This is what lets a consumer walk a
    station's visit history and reconstruct exactly the shift-change
    boundaries, without needing raw event data threaded in separately."""
    machine_wear_state: float
    ambient_conditions: AmbientConditions

    @property
    def dwell_time_s(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds()


class CarTwin(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    car_id: str
    model_variant: str
    entry_timestamp: datetime
    visits: list[StationVisit] = Field(default_factory=list)

    def record_visit(self, visit: StationVisit) -> None:
        """Appends a new visit. This is the only sanctioned way to grow a
        CarTwin's history -- existing visits are never edited or removed."""
        self.visits.append(visit)
