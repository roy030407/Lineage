"""Prediction outcome tracking: did a RiskAssessment's HIGH-risk alarm
actually materialize as an inspection failure? In-memory, append-only,
same convention as act.ledger.AuditLedger -- no database, no edits, no
deletes.

Ground truth comes from a run's inspection.csv (result == "fail" for a
given (car_id, station_id)), the same join key scripts/train_risk_model.py
already uses to label training data -- this reuses that join, not a new
source of truth.
"""

from datetime import datetime
from enum import StrEnum
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from lineage.common.types import RiskLevel
from lineage.config.specs import LineSpec
from lineage.predict.risk import RiskModel, assess_risk
from lineage.twin.genealogy import GenealogyStore


class PredictionOutcome(StrEnum):
    PENDING = "pending"
    MATERIALIZED = "materialized"
    NOT_MATERIALIZED = "not_materialized"


class PredictionRecord(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    car_id: str
    station_id: str
    model_version: str
    risk_level: RiskLevel
    probability: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    predicted_at: datetime
    """The car's arrival time at `station_id` -- the point at which this
    station's actual result becomes knowable. assess_risk itself is meant to
    run using only upstream data available *before* that moment; this ledger
    is built retrospectively from a completed run, so there's no earlier,
    equally-precise timestamp to anchor to. Documented rather than hidden."""
    outcome: PredictionOutcome = PredictionOutcome.PENDING
    resolved_at: datetime | None = None
    actual_result: str | None = None  # "pass" | "fail", from inspection.csv


class PredictionLedger:
    """In-memory, append-only. No database, no edits, no deletes."""

    def __init__(self) -> None:
        self._records: list[PredictionRecord] = []

    def record(self, prediction_record: PredictionRecord) -> None:
        self._records.append(prediction_record)

    def all_records(self) -> list[PredictionRecord]:
        return list(self._records)


def _resolve(record: PredictionRecord) -> PredictionRecord:
    """A HIGH-risk alarm materializes if the actual result was a fail;
    anything else (LOW/MEDIUM predicted, or HIGH predicted but the car
    passed) is scored as not-materialized. UNKNOWN_RISK is never passed in
    here at all -- build_ledger_from_run skips it before this point."""
    materialized = record.risk_level == RiskLevel.HIGH and record.actual_result == "fail"
    outcome = PredictionOutcome.MATERIALIZED if materialized else PredictionOutcome.NOT_MATERIALIZED
    return record.model_copy(update={"outcome": outcome, "resolved_at": record.predicted_at})


def build_ledger_from_run(
    line: LineSpec, store: GenealogyStore, run_dir: Path, model: RiskModel
) -> PredictionLedger:
    """Retrospectively assesses every car against every inspection station it
    reached, then immediately resolves each assessment against that run's
    recorded inspection result -- this is a completed run, so prediction and
    resolution happen in the same pass rather than a live pending state."""
    inspection_station_ids = [s.id for s in line.stations if s.is_inspection_station]
    inspection_df = pd.read_csv(run_dir / "inspection.csv", parse_dates=["timestamp"])
    result_by_key = {
        (row.car_id, row.station_id): row.result for row in inspection_df.itertuples()
    }

    ledger = PredictionLedger()
    for car_id in store.all_car_ids():
        twin = store.car(car_id)
        for station_id in inspection_station_ids:
            actual_result = result_by_key.get((car_id, station_id))
            if actual_result is None:
                continue  # car never reached this inspection station

            assessment = assess_risk(
                car=twin,
                line=line,
                store=store,
                inspection_station_id=station_id,
                model=model,
            )
            if assessment.risk_level == RiskLevel.UNKNOWN_RISK:
                continue  # nothing actionable to score

            visit = next((v for v in twin.visits if v.station_id == station_id), None)
            if visit is None:
                continue

            record = PredictionRecord(
                car_id=car_id,
                station_id=station_id,
                model_version=assessment.model_version,
                risk_level=assessment.risk_level,
                probability=assessment.probability,
                confidence=assessment.confidence,
                predicted_at=visit.entry_time,
                actual_result=actual_result,
            )
            ledger.record(_resolve(record))

    return ledger


class LedgerMetrics(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    sample_size: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float | None = Field(default=None, ge=0, le=1)
    recall: float | None = Field(default=None, ge=0, le=1)
    false_alarm_rate: float | None = Field(default=None, ge=0, le=1)
    """False positive rate: FP / (FP + TN) -- of the cars that actually
    passed, what fraction did this model alarm on anyway."""
    trust_score: float | None = Field(default=None, ge=0, le=1)
    """F1 (the harmonic mean of precision and recall) -- a defensible,
    standard single-number summary, not a domain-specific formula; there is
    no one fixed definition of "trust score" so this is a judgment call,
    named here rather than left implicit."""


def compute_metrics(
    records: list[PredictionRecord],
    *,
    station_id: str | None = None,
    model_version: str | None = None,
) -> LedgerMetrics:
    resolved = [r for r in records if r.outcome != PredictionOutcome.PENDING]
    if station_id is not None:
        resolved = [r for r in resolved if r.station_id == station_id]
    if model_version is not None:
        resolved = [r for r in resolved if r.model_version == model_version]

    tp = sum(1 for r in resolved if r.risk_level == RiskLevel.HIGH and r.actual_result == "fail")
    fp = sum(1 for r in resolved if r.risk_level == RiskLevel.HIGH and r.actual_result == "pass")
    fn = sum(1 for r in resolved if r.risk_level != RiskLevel.HIGH and r.actual_result == "fail")
    tn = sum(1 for r in resolved if r.risk_level != RiskLevel.HIGH and r.actual_result == "pass")

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    false_alarm_rate = fp / (fp + tn) if (fp + tn) > 0 else None
    trust_score = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )

    return LedgerMetrics(
        sample_size=len(resolved),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        false_alarm_rate=false_alarm_rate,
        trust_score=trust_score,
    )


class TrendState(StrEnum):
    IMPROVING = "improving"
    STAGNANT = "stagnant"
    WORSENING = "worsening"


def classify_post_intervention_trend(
    records: list[PredictionRecord],
    station_id: str,
    intervention_at: datetime,
    window_size: int = 10,
    stagnant_threshold: float = 0.05,
) -> TrendState | None:
    """Compares trust_score over the `window_size` resolved predictions for
    `station_id` immediately before vs. after `intervention_at`. Returns
    None -- not a verdict -- if either side has fewer than `window_size`
    records yet; a trend classification manufactured from too little data
    would be worse than no answer."""
    relevant = (
        r for r in records if r.station_id == station_id and r.outcome != PredictionOutcome.PENDING
    )
    station_records = sorted(relevant, key=lambda r: r.predicted_at)
    before = [r for r in station_records if r.predicted_at < intervention_at][-window_size:]
    after = [r for r in station_records if r.predicted_at >= intervention_at][:window_size]

    if len(before) < window_size or len(after) < window_size:
        return None

    before_score = compute_metrics(before).trust_score
    after_score = compute_metrics(after).trust_score
    if before_score is None or after_score is None:
        return None

    diff = after_score - before_score
    if diff > stagnant_threshold:
        return TrendState.IMPROVING
    if diff < -stagnant_threshold:
        return TrendState.WORSENING
    return TrendState.STAGNANT
