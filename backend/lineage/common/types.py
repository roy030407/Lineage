"""Shared enums and ID/timestamp types (e.g. RiskLevel, including UNKNOWN)."""

from enum import StrEnum


class RiskLevel(StrEnum):
    """A station with no sensor, or a prediction with insufficient coverage,
    is UNKNOWN_RISK -- never a numeric level and never treated as safe."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN_RISK = "unknown_risk"
