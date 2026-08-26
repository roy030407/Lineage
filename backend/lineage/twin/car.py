"""Car model: serial/VIN, spec variant, per-station entry/exit timestamps."""

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
