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
    is_inspection_station: bool = False
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
        recomputing the conveyor distance between them as the actual Euclidean
        distance between their (unchanged) coordinates -- not the sum of the
        two segments it used to sit between. Those agree when the removed
        station was collinear with its neighbours, but a real, found bug: they
        diverge at any turn (a zone-transition corner, for instance), where
        the sum overstates the straight-line distance between two points that
        never moved."""
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
            prev_coord = self.layout.coordinate_for(prev_station.id)
            next_coord = self.layout.coordinate_for(next_station.id)
            distance = (
                (next_coord.x_m - prev_coord.x_m) ** 2 + (next_coord.y_m - prev_coord.y_m) ** 2
            ) ** 0.5
            segments.append(
                ConveyorSegment(
                    from_station_id=prev_station.id,
                    to_station_id=next_station.id,
                    distance_m=distance,
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

    def prepend_station(self, spec: StationSpec) -> "LineSpec":
        """Insert `spec` before the current first station, extrapolating the
        new layout coordinate and conveyor distance backward along the
        line's existing direction -- insert_station has no equivalent
        (after_station_id=None there only ever means tail-append; there's no
        "insert at head" short of this)."""
        stations = list(self.stations)
        if len(stations) < 2:
            raise ValueError(
                "cannot prepend: need at least 2 existing stations to extrapolate "
                "a layout direction"
            )

        first, second = stations[0], stations[1]
        first_coord = self.layout.coordinate_for(first.id)
        second_coord = self.layout.coordinate_for(second.id)
        dx = first_coord.x_m - second_coord.x_m
        dy = first_coord.y_m - second_coord.y_m
        new_coord = StationCoordinate(
            station_id=spec.id, x_m=first_coord.x_m + dx, y_m=first_coord.y_m + dy
        )

        first_segment = self.layout.segment_between(first.id, second.id)
        if first_segment is None:
            raise ValueError(
                f"no conveyor segment between {first.id!r} and {second.id!r} to "
                "extrapolate head-prepend distance from"
            )
        new_segment = ConveyorSegment(
            from_station_id=spec.id, to_station_id=first.id, distance_m=first_segment.distance_m
        )

        coords = [*self.layout.coordinates, new_coord]
        segments = [*self.layout.segments, new_segment]

        new_stations = [spec, *stations]
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

    def set_segment_distance(
        self, from_station_id: str, to_station_id: str, distance_m: float
    ) -> "LineSpec":
        """Rescales the segment from `from_station_id` to `to_station_id` to
        `distance_m` by moving `to_station_id` along the segment's existing
        direction vector -- distance_m is authoritative, the coordinate is
        derived from it, never the other way, so the geometry invariant holds
        by construction rather than needing a separate check.

        Every station from `to_station_id` onward (its whole downstream
        chain) is translated by the same delta this produces, not just
        `to_station_id` itself -- moving one station alone would silently
        change every *other* segment's real distance out from under its
        still-unchanged distance_m the moment the path isn't perfectly
        straight, exactly the kind of drift this method exists to prevent.
        A rigid translation preserves every pairwise distance within the
        translated group, so only the one edited segment's distance
        actually changes.
        """
        if distance_m <= 0:
            raise ValueError("distance_m must be > 0")
        segment = self.layout.segment_between(from_station_id, to_station_id)
        if segment is None:
            raise ValueError(
                f"no conveyor segment between {from_station_id!r} and {to_station_id!r}"
            )

        from_coord = self.layout.coordinate_for(from_station_id)
        to_coord = self.layout.coordinate_for(to_station_id)
        dx = to_coord.x_m - from_coord.x_m
        dy = to_coord.y_m - from_coord.y_m
        current_length = (dx**2 + dy**2) ** 0.5
        if current_length == 0:
            raise ValueError(
                f"cannot rescale a zero-length segment between {from_station_id!r} "
                f"and {to_station_id!r}"
            )
        scale = distance_m / current_length
        new_to_x = from_coord.x_m + dx * scale
        new_to_y = from_coord.y_m + dy * scale
        delta_x = new_to_x - to_coord.x_m
        delta_y = new_to_y - to_coord.y_m

        to_idx = next(i for i, s in enumerate(self.stations) if s.id == to_station_id)
        downstream_ids = {s.id for s in self.stations[to_idx:]}

        coords = [
            (
                StationCoordinate(station_id=c.station_id, x_m=c.x_m + delta_x, y_m=c.y_m + delta_y)
                if c.station_id in downstream_ids
                else c
            )
            for c in self.layout.coordinates
        ]
        segments = [
            (
                ConveyorSegment(
                    from_station_id=from_station_id,
                    to_station_id=to_station_id,
                    distance_m=distance_m,
                )
                if s is segment
                else s
            )
            for s in self.layout.segments
        ]

        new_layout = LayoutSpec(coordinates=coords, segments=segments)
        return LineSpec(
            plant_name=self.plant_name,
            site=self.site,
            stations=self.stations,
            layout=new_layout,
            environment_envelope=self.environment_envelope,
        )

    def replace_station(self, station_id: str, updated: StationSpec) -> "LineSpec":
        """Swaps in `updated` for the station currently at `station_id`,
        keeping its position and the rest of the line's topology/layout
        untouched -- for editing a station's own fields (sensors,
        acquisition_mode, commissioning_baseline, ...) without an
        insert/remove/move. `updated.id` must still equal `station_id`;
        renaming a station through this method isn't supported. Constructs a
        fresh LineSpec so every cross-station validator (duplicate sensor
        ids, etc.) re-runs, not just `updated`'s own."""
        idx = next((i for i, s in enumerate(self.stations) if s.id == station_id), None)
        if idx is None:
            raise ValueError(f"unknown station_id {station_id!r}")
        if updated.id != station_id:
            raise ValueError(f"replace_station cannot rename {station_id!r} to {updated.id!r}")

        new_stations = list(self.stations)
        new_stations[idx] = updated.model_copy(update={"sequence_index": idx})
        return LineSpec(
            plant_name=self.plant_name,
            site=self.site,
            stations=new_stations,
            layout=self.layout,
            environment_envelope=self.environment_envelope,
        )

    def with_environment_envelope(self, envelope: EnvironmentEnvelope) -> "LineSpec":
        return LineSpec(
            plant_name=self.plant_name,
            site=self.site,
            stations=self.stations,
            layout=self.layout,
            environment_envelope=envelope,
        )

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json")
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "LineSpec":
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return cls.model_validate(data)
