"""TraceResult and CausalChain Pydantic models."""

from pydantic import BaseModel, ConfigDict, Field


class ContributionCause(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    contribution_score: float = Field(ge=0, le=1)
    verifiable: bool
    deviation_z: float | None = None


class ExposedCar(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    car_id: str
    exposure_confidence: float = Field(ge=0, le=1)


class TraceResult(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    car_id: str
    originating_station_id: str
    originating_is_verifiable: bool
    ranked_contributions: list[ContributionCause] = Field(default_factory=list)
    affected_cars: list[ExposedCar] = Field(default_factory=list)
