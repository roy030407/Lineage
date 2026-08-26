"""Shared types for the Act layer: proposals, predicted effects, and the
immutable audit trail. Not scaffolded originally as act/models.py -- added
here, matching the pattern already used by datagen/predict/replay."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ApproverRole(StrEnum):
    OPERATOR = "operator"
    FLOOR_SUPERVISOR = "floor_supervisor"
    PLANT_MANAGER = "plant_manager"
    LEADERSHIP = "leadership"


ROLE_RANK: dict[ApproverRole, int] = {
    ApproverRole.OPERATOR: 0,
    ApproverRole.FLOOR_SUPERVISOR: 1,
    ApproverRole.PLANT_MANAGER: 2,
    ApproverRole.LEADERSHIP: 3,
}
MINIMUM_APPROVER_ROLE = ApproverRole.FLOOR_SUPERVISOR


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Proposal(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    proposal_id: str
    station_id: str
    parameter_name: str
    current_value: float
    proposed_value: float
    rationale: str
    trace_car_id: str
    requires_physical_change: bool
    next_maintenance_window: datetime | None = None
    status: ProposalStatus = ProposalStatus.PENDING


class PredictedEffect(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    proposal_id: str
    predicted_defect_rate_delta: float
    defect_rate_confidence_interval: tuple[float, float]
    predicted_throughput_delta: float
    throughput_confidence_interval: tuple[float, float]


class AuditRecord(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    proposal_id: str
    approver_role: ApproverRole
    approver_id: str
    decision: str
    timestamp: datetime
    proposal_snapshot: Proposal
