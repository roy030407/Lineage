"""Prediction ledger endpoints. The ledger is built lazily, on first request,
and cached on AppState from then on -- never recomputed per request, and
deliberately not built eagerly at 'load' time (assessing every car against
every inspection station it reached is real work: ~105s observed for a
400-car run, and 'load' is expected to stay fast). See api/routes/mirror.py
for where the cache gets invalidated on a new 'load'.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from lineage.api.deps import AppState, get_app_state
from lineage.predict.ledger import (
    LedgerMetrics,
    PredictionLedger,
    TrendState,
    build_ledger_from_run,
    classify_post_intervention_trend,
    compute_metrics,
)
from lineage.predict.risk import RiskModel

router = APIRouter()


def _ensure_ledger(state: AppState) -> PredictionLedger:
    if state.prediction_ledger is not None:
        return state.prediction_ledger

    if state.engine is None or state.genealogy_store is None or state.current_run_dir is None:
        raise HTTPException(
            status_code=409, detail="no run loaded; send action='load' first"
        )
    assert state.line is not None  # a loaded engine implies a loaded line

    with state.prediction_ledger_lock:
        # Re-check now that we hold the lock: another request may have
        # finished the ~105s build while we were waiting for it, in which
        # case there is nothing left for this request to do but return it.
        if state.prediction_ledger is not None:
            return state.prediction_ledger

        try:
            model = RiskModel(state.models_root / "risk_v1")
            ledger = build_ledger_from_run(
                state.line, state.genealogy_store, state.current_run_dir, model
            )
        except Exception as exc:
            # data/models/ is gitignored (a locally-trained artifact, not
            # committed), so "no trained risk model" is the expected case in
            # a fresh clone or CI -- surfaced clearly, not a silently empty
            # ledger.
            raise HTTPException(
                status_code=409,
                detail="no prediction ledger available -- no trained risk model was found "
                "under data/models/risk_v1",
            ) from exc

        state.prediction_ledger = ledger
        return ledger


@router.get("/api/predict/metrics")
def get_metrics(
    station_id: str | None = None,
    model_version: str | None = None,
    state: AppState = Depends(get_app_state),
) -> LedgerMetrics:
    ledger = _ensure_ledger(state)
    return compute_metrics(
        ledger.all_records(), station_id=station_id, model_version=model_version
    )


@router.get("/api/predict/metrics/by_station")
def get_metrics_by_station(state: AppState = Depends(get_app_state)) -> dict[str, LedgerMetrics]:
    ledger = _ensure_ledger(state)
    records = ledger.all_records()
    station_ids = sorted({r.station_id for r in records})
    return {
        station_id: compute_metrics(records, station_id=station_id)
        for station_id in station_ids
    }


@router.get("/api/predict/trend/{station_id}")
def get_trend(
    station_id: str,
    intervention_at: datetime,
    window_size: int = 10,
    state: AppState = Depends(get_app_state),
) -> TrendState | None:
    ledger = _ensure_ledger(state)
    return classify_post_intervention_trend(
        ledger.all_records(), station_id, intervention_at, window_size=window_size
    )
