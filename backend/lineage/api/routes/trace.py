"""Root-cause trace query endpoints.

The same trace.lineage_query.trace call scripts/demo.py used to invoke
directly in Python, exposed over the API so the frontend (CarPanel's
"Trace root cause") and the demo drive the exact same code path.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from lineage.api.deps import AppState, get_app_state
from lineage.trace.lineage_query import trace

router = APIRouter()


class TraceContribution(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    score: float
    deviation_z: float | None = None
    is_verifiable: bool


class TraceExposedCar(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    car_id: str
    confidence: float


class TraceResponse(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    flagged_car_id: str
    originating_station_id: str | None
    originating_is_verifiable: bool
    contributions: list[TraceContribution]
    exposed_cohort: list[TraceExposedCar]


@router.get("/api/trace/{car_id}")
def trace_car(
    car_id: str,
    station_id: str | None = None,
    state: AppState = Depends(get_app_state),
) -> TraceResponse:
    """Traces `car_id` back through every upstream station it visited.

    `station_id` optionally pins where the car was flagged (an inspection
    station, typically); left out, the trace runs from the car's most
    recently visited station -- "trace it back from wherever it is now".
    """
    if state.engine is None or state.genealogy_store is None:
        raise HTTPException(status_code=409, detail="no run loaded; send action='load' first")
    assert state.line is not None  # a loaded engine implies a loaded line

    try:
        twin = state.genealogy_store.car(car_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown car {car_id!r}") from exc

    if station_id is None:
        if not twin.visits:
            raise HTTPException(status_code=404, detail=f"car {car_id!r} has no visits yet")
        station_id = max(twin.visits, key=lambda v: v.entry_time).station_id
    elif all(v.station_id != station_id for v in twin.visits):
        raise HTTPException(
            status_code=404, detail=f"car {car_id!r} never visited station {station_id!r}"
        )

    result = trace(
        line=state.line,
        store=state.genealogy_store,
        car_id=car_id,
        flagged_at_station_id=station_id,
    )
    return TraceResponse(
        flagged_car_id=result.car_id,
        originating_station_id=result.originating_station_id,
        originating_is_verifiable=result.originating_is_verifiable,
        contributions=[
            TraceContribution(
                station_id=c.station_id,
                score=c.contribution_score,
                deviation_z=c.deviation_z,
                is_verifiable=c.verifiable,
            )
            for c in result.ranked_contributions
        ],
        exposed_cohort=[
            TraceExposedCar(car_id=c.car_id, confidence=c.exposure_confidence)
            for c in result.affected_cars
        ],
    )
