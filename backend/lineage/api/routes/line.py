"""LineSpec CRUD endpoints (backing the station builder UI)."""

from fastapi import APIRouter, Depends, HTTPException

from lineage.api.deps import AppState, get_app_state

router = APIRouter()


@router.get("/api/line")
def get_line(state: AppState = Depends(get_app_state)) -> dict:
    if state.line is None:
        raise HTTPException(status_code=404, detail="no line loaded")
    return state.line.model_dump(mode="json")
