"""RiskAssessment and related Pydantic result types (risk level + confidence, always both)."""

from pydantic import BaseModel, ConfigDict, Field

from lineage.common.types import RiskLevel


class FeatureVector(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    car_id: str
    target_station_id: str
    feature_names: list[str]
    values: list[float]
    coverage_fraction: float = Field(ge=0, le=1)


class RiskAssessment(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    car_id: str
    station_id: str
    risk_level: RiskLevel
    probability: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    coverage_fraction: float = Field(ge=0, le=1)
    model_version: str
