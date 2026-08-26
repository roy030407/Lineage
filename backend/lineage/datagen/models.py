"""Pydantic models for run generation: RunConfig/RunArtifacts and the ground-truth
records that make Predict/Trace gradeable against a known answer key."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lineage.config.specs import Zone


class DefectMechanism(StrEnum):
    TORQUE_DRIFT = "torque_drift"
    ENVIRONMENTAL_EXCURSION = "environmental_excursion"
    OPERATOR_HANDOVER_SHIFT = "operator_handover_shift"
    MATERIAL_QUALITY = "material_quality"
    WEAR = "wear"


SEEDABLE_MECHANISMS = (DefectMechanism.TORQUE_DRIFT,)
"""DefectSeed exists only for mechanisms with no natural background pathway.
ENVIRONMENTAL_EXCURSION has its own EnvironmentExcursion model (ambient temp
vs. envelope), OPERATOR_HANDOVER_SHIFT arises organically from the operator
shift schedule/profiles, MATERIAL_QUALITY and WEAR are fully organic. Only
TORQUE_DRIFT needs a direct injection, since ordinary wear drift stays
negligible over a run this short relative to realistic maintenance intervals.
"""


class DefectSeed(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    id: str
    mechanism: DefectMechanism
    station_id: str
    onset_car_index: int = Field(ge=0)
    duration_cars: int = Field(default=1, ge=1)
    severity: float
    surfaces_after_inspections: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _check_mechanism(self) -> "DefectSeed":
        if self.mechanism not in SEEDABLE_MECHANISMS:
            allowed = [m.value for m in SEEDABLE_MECHANISMS]
            raise ValueError(
                f"DefectSeed.mechanism must be one of {allowed}, got {self.mechanism.value!r}"
            )
        return self


class EnvironmentExcursion(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    id: str
    zone: Zone
    start_car_index: int = Field(ge=0)
    end_car_index: int = Field(ge=0)
    temp_c: float
    surfaces_after_inspections: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _check_range(self) -> "EnvironmentExcursion":
        if self.end_car_index < self.start_car_index:
            raise ValueError("end_car_index must be >= start_car_index")
        return self


class OperatorProfile(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    operator_id: str
    bias: float
    std: float = Field(gt=0)


class ShiftAssignment(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    operator_id: str
    start_car_index: int = Field(ge=0)
    end_car_index: int = Field(ge=0)
    handover_flagged: bool = False

    @model_validator(mode="after")
    def _check_range(self) -> "ShiftAssignment":
        if self.end_car_index < self.start_car_index:
            raise ValueError("end_car_index must be >= start_car_index")
        return self


class RunConfig(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    run_id: str
    random_seed: int
    num_cars: int = Field(gt=0)
    background_defect_rate: float = Field(ge=0, le=1)
    defect_z_threshold: float = 3.0
    defect_seeds: list[DefectSeed] = Field(default_factory=list)
    environment_excursions: list[EnvironmentExcursion] = Field(default_factory=list)
    baseline_temp_c: float
    operator_profiles: list[OperatorProfile] = Field(default_factory=list)
    operator_shift_schedule: list[ShiftAssignment] = Field(default_factory=list)
    sim_start_time: datetime = datetime(2024, 1, 1)
    manual_report_probability: float = Field(default=0.85, ge=0, le=1)
    conveyor_speed_mps: float = Field(default=0.5, gt=0)
    buffer_capacity: int = Field(default=3, ge=1)
    maintenance_events: dict[str, list[datetime]] = Field(default_factory=dict)
    """station_id -> in-run maintenance timestamps, resetting wear at each one."""


class RunArtifacts(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    run_id: str
    output_dir: Path
    telemetry_path: Path
    events_path: Path
    inspection_path: Path
    ground_truth_path: Path
    run_config_path: Path
    num_cars: int


class InvalidWindow(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    start_car_index: int
    end_car_index: int
    temp_c: float


class GroundTruthDefect(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    defect_id: str
    mechanism: DefectMechanism
    origin_station_id: str
    onset_timestamp: datetime
    cars_exposed: list[str]
    detected: bool
    detected_at_station_id: str | None = None
    detected_at_timestamp: datetime | None = None


class GroundTruth(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    run_id: str
    seed: int
    environment_valid: bool
    invalid_windows: list[InvalidWindow] = Field(default_factory=list)
    defects: list[GroundTruthDefect] = Field(default_factory=list)
