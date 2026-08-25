"""Pydantic models: LineSpec, StationSpec, SensorSpec, with to_yaml()/from_yaml()."""

from datetime import date
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SensorKind(StrEnum):
    THERMAL = "thermal"
    INFRARED = "infrared"
    VIBRATION = "vibration"
    TORQUE = "torque"
    RPM = "rpm"
    CYCLE_TIME = "cycle_time"
    NONE = "none"


class SensorSpec(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    id: str
    kind: SensorKind
    unit: str
    sample_rate_hz: float = Field(gt=0)
    install_date: date
    last_calibration_date: date
    accuracy_class: str


class ConditionStats(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    mean: dict[str, float] = Field(default_factory=dict)
    std: dict[str, float] = Field(default_factory=dict)


class CommissioningBaseline(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    idle: ConditionStats
    loaded: ConditionStats


class MachineSpec(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    model: str
    install_year: int
    last_maintenance_date: date
    maintenance_interval_days: int = Field(gt=0)
    wear_curve_shape: str


class ParamRange(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    min: float
    max: float
    step: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_bounds(self) -> "ParamRange":
        if self.min >= self.max:
            raise ValueError(f"ParamRange min ({self.min}) must be < max ({self.max})")
        return self


class Zone(StrEnum):
    BODY = "body"
    PAINT = "paint"
    FINAL = "final"


class AcquisitionMode(StrEnum):
    INSTRUMENTED = "instrumented"
    MANUAL = "manual"
    MIXED = "mixed"


class StationSpec(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    id: str
    name: str
    zone: Zone
    sequence_index: int = Field(ge=0)
    sensors: list[SensorSpec] = Field(default_factory=list)
    acquisition_mode: AcquisitionMode
    cycle_time_nominal_s: float = Field(gt=0)
    commissioning_baseline: CommissioningBaseline | None = None
    changeable_params: dict[str, ParamRange] = Field(default_factory=dict)
    readable_params: list[str] = Field(default_factory=list)
    machine: MachineSpec
    cost_per_hour: float = Field(ge=0)
    value_add_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _check_sensors_match_acquisition_mode(self) -> "StationSpec":
        if self.acquisition_mode == AcquisitionMode.MANUAL and self.sensors:
            raise ValueError(f"station {self.id!r} is manual and must not declare sensors")
        if (
            self.acquisition_mode in (AcquisitionMode.INSTRUMENTED, AcquisitionMode.MIXED)
            and not self.sensors
        ):
            raise ValueError(
                f"station {self.id!r} is {self.acquisition_mode.value} "
                "and requires at least one sensor"
            )
        return self

    @model_validator(mode="after")
    def _check_sensor_ids_unique_within_station(self) -> "StationSpec":
        ids = [s.id for s in self.sensors]
        if len(ids) != len(set(ids)):
            raise ValueError(f"station {self.id!r} has duplicate sensor ids")
        return self


class StationCoordinate(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    x_m: float
    y_m: float


class ConveyorSegment(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    from_station_id: str
    to_station_id: str
    distance_m: float = Field(gt=0)


class LayoutSpec(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    coordinates: list[StationCoordinate] = Field(default_factory=list)
    segments: list[ConveyorSegment] = Field(default_factory=list)

    def coordinate_for(self, station_id: str) -> StationCoordinate:
        for c in self.coordinates:
            if c.station_id == station_id:
                return c
        raise KeyError(f"no layout coordinate for station {station_id!r}")

    def segment_between(self, from_id: str, to_id: str) -> ConveyorSegment | None:
        for s in self.segments:
            if s.from_station_id == from_id and s.to_station_id == to_id:
                return s
        return None


class EnvironmentEnvelope(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    temp_min_c: float
    temp_max_c: float
    humidity_min_pct: float = Field(ge=0, le=100)
    humidity_max_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _check_ranges(self) -> "EnvironmentEnvelope":
        if self.temp_min_c >= self.temp_max_c:
            raise ValueError("environment envelope temp_min_c must be < temp_max_c")
        if self.humidity_min_pct >= self.humidity_max_pct:
            raise ValueError("environment envelope humidity_min_pct must be < humidity_max_pct")
        return self


class LineSpec(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    plant_name: str
    site: str
    stations: list[StationSpec]
    layout: LayoutSpec
    environment_envelope: EnvironmentEnvelope

    @model_validator(mode="after")
    def _check_stations(self) -> "LineSpec":
        ids = [s.id for s in self.stations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate station ids in LineSpec")

        expected_indices = list(range(len(self.stations)))
        actual_indices = [s.sequence_index for s in self.stations]
        if actual_indices != expected_indices:
            raise ValueError(
                "station list order must match sequence_index, contiguous from 0: "
                f"got {actual_indices}"
            )

        sensor_ids = [sensor.id for s in self.stations for sensor in s.sensors]
        if len(sensor_ids) != len(set(sensor_ids)):
            raise ValueError("duplicate sensor ids across LineSpec")

        return self

    def insert_station(self, spec: StationSpec, after_station_id: str | None) -> "LineSpec":
        """Insert `spec` after the station with id `after_station_id`.

        `after_station_id=None` appends after the current last station, extrapolating
        the new layout coordinate and conveyor distance along the line's existing
        direction (there is no downstream segment to split in that case).
        """
        stations = list(self.stations)
        coords = list(self.layout.coordinates)
        segments = list(self.layout.segments)

        if after_station_id is None:
            insert_at = len(stations)
            if not stations:
                new_coord = StationCoordinate(station_id=spec.id, x_m=0.0, y_m=0.0)
                new_segment = None
            elif len(stations) == 1:
                raise ValueError(
                    "cannot append after_station_id=None: need at least 2 existing "
                    "stations to extrapolate a layout direction"
                )
            else:
                last = stations[-1]
                second_last = stations[-2]
                last_coord = self.layout.coordinate_for(last.id)
                second_last_coord = self.layout.coordinate_for(second_last.id)
                dx = last_coord.x_m - second_last_coord.x_m
                dy = last_coord.y_m - second_last_coord.y_m
                new_coord = StationCoordinate(
                    station_id=spec.id, x_m=last_coord.x_m + dx, y_m=last_coord.y_m + dy
                )
                last_segment = self.layout.segment_between(second_last.id, last.id)
                if last_segment is None:
                    raise ValueError(
                        f"no conveyor segment between {second_last.id!r} and {last.id!r} "
                        "to extrapolate tail-append distance from"
                    )
                new_segment = ConveyorSegment(
                    from_station_id=last.id,
                    to_station_id=spec.id,
                    distance_m=last_segment.distance_m,
                )
            coords.append(new_coord)
            if new_segment is not None:
                segments.append(new_segment)
        else:
            after_idx = next(
                (i for i, s in enumerate(stations) if s.id == after_station_id), None
            )
            if after_idx is None:
                raise ValueError(f"unknown after_station_id {after_station_id!r}")
            if after_idx == len(stations) - 1:
                raise ValueError(
                    "insert_station cannot append after the last station via "
                    "after_station_id; pass after_station_id=None to append at the tail"
                )
            after = stations[after_idx]
            following = stations[after_idx + 1]
            insert_at = after_idx + 1

            old_segment = self.layout.segment_between(after.id, following.id)
            if old_segment is None:
                raise ValueError(
                    f"no conveyor segment between {after.id!r} and {following.id!r} to split"
                )
            half = old_segment.distance_m / 2
            segments = [s for s in segments if s is not old_segment]
            segments.append(
                ConveyorSegment(from_station_id=after.id, to_station_id=spec.id, distance_m=half)
            )
            segments.append(
                ConveyorSegment(
                    from_station_id=spec.id, to_station_id=following.id, distance_m=half
                )
            )

            after_coord = self.layout.coordinate_for(after.id)
            following_coord = self.layout.coordinate_for(following.id)
            new_coord = StationCoordinate(
                station_id=spec.id,
                x_m=(after_coord.x_m + following_coord.x_m) / 2,
                y_m=(after_coord.y_m + following_coord.y_m) / 2,
            )
            coords.append(new_coord)

        new_stations = stations[:insert_at] + [spec] + stations[insert_at:]
        new_stations = [
            s.model_copy(update={"sequence_index": i}) for i, s in enumerate(new_stations)
        ]

        new_layout = LayoutSpec(coordinates=coords, segments=segments)

        return LineSpec(
            plant_name=self.plant_name,
            site=self.site,
            stations=new_stations,
            layout=new_layout,
            environment_envelope=self.environment_envelope,
        )

    def remove_station(self, station_id: str) -> "LineSpec":
        """Remove the station with id `station_id`, rejoining its neighbours and
        recomputing the conveyor distance between them as the sum of the two
        segments it used to sit between."""
        stations = list(self.stations)
        idx = next((i for i, s in enumerate(stations) if s.id == station_id), None)
        if idx is None:
            raise ValueError(f"unknown station_id {station_id!r}")

        removed = stations[idx]
        prev_station = stations[idx - 1] if idx > 0 else None
        next_station = stations[idx + 1] if idx + 1 < len(stations) else None

        coords = [c for c in self.layout.coordinates if c.station_id != removed.id]
        segments = list(self.layout.segments)

        seg_in = (
            self.layout.segment_between(prev_station.id, removed.id) if prev_station else None
        )
        seg_out = (
            self.layout.segment_between(removed.id, next_station.id) if next_station else None
        )
        segments = [s for s in segments if s is not seg_in and s is not seg_out]

        if prev_station is not None and next_station is not None:
            if seg_in is None or seg_out is None:
                raise ValueError(
                    f"missing conveyor segment(s) around {station_id!r} to rejoin neighbours"
                )
            segments.append(
                ConveyorSegment(
                    from_station_id=prev_station.id,
                    to_station_id=next_station.id,
                    distance_m=seg_in.distance_m + seg_out.distance_m,
                )
            )
        # if removed was the first or last station, the single adjoining segment is
        # simply dropped: there is nothing to rejoin it to.

        new_stations = [s for s in stations if s.id != station_id]
        new_stations = [
            s.model_copy(update={"sequence_index": i}) for i, s in enumerate(new_stations)
        ]

        new_layout = LayoutSpec(coordinates=coords, segments=segments)

        return LineSpec(
            plant_name=self.plant_name,
            site=self.site,
            stations=new_stations,
            layout=new_layout,
            environment_envelope=self.environment_envelope,
        )

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json")
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "LineSpec":
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return cls.model_validate(data)
