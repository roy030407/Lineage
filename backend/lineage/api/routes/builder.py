"""Station builder: edit a draft LineSpec (insert/remove/reorder stations)
and save it as a new line file. Operates on AppState.builder_draft, a
LineSpec independent of whatever `state.line` a Mirror session has loaded
for replay -- editing never disturbs a running session.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from lineage.api.deps import AppState, get_app_state
from lineage.config.specs import LineSpec, StationSpec

router = APIRouter()


def _require_draft(state: AppState) -> LineSpec:
    if state.builder_draft is None:
        raise HTTPException(
            status_code=409, detail="no draft started; POST /api/builder/draft/start first"
        )
    return state.builder_draft


def _move_station(line: LineSpec, station_id: str, direction: Literal["up", "down"]) -> LineSpec:
    """Reorders by removing and reinserting the station via the existing,
    already-tested insert_station/remove_station -- rewriting conveyor
    segment topology by hand here would just be a worse reimplementation of
    what those already do correctly.

    insert_station has no "insert at the head" operation (after_station_id
    picks a station to follow; None always means "append at the tail"), so
    moving a station into the very first position isn't supported -- the
    caller gets a clear 400 for that rather than a silently wrong result."""
    ids = [s.id for s in line.stations]
    if station_id not in ids:
        raise ValueError(f"unknown station_id {station_id!r}")
    idx = ids.index(station_id)

    if direction == "up":
        if idx <= 1:
            raise ValueError(
                "cannot move this station further up: moving a station into the first "
                "position isn't supported (insert_station has no 'insert at head' operation)"
            )
        target_after_id = ids[idx - 2]
    else:
        if idx >= len(ids) - 1:
            raise ValueError("cannot move this station further down: it is already last")
        target_after_id = ids[idx + 1]

    station = next(s for s in line.stations if s.id == station_id)
    without = line.remove_station(station_id)
    remaining_ids = [s.id for s in without.stations]
    # If the station we're re-inserting after is now the last remaining one,
    # insert_station requires after_station_id=None (tail-append) instead.
    after_arg: str | None = target_after_id
    if remaining_ids and remaining_ids[-1] == target_after_id:
        after_arg = None
    return without.insert_station(station, after_station_id=after_arg)


class InsertStationRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station: StationSpec
    after_station_id: str | None = None


class MoveStationRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    direction: Literal["up", "down"]


class SaveDraftRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    filename: str


@router.post("/api/builder/draft/start")
def start_draft(state: AppState = Depends(get_app_state)) -> LineSpec:
    if state.line is None:
        raise HTTPException(status_code=409, detail="no line loaded to start a draft from")
    state.builder_draft = state.line
    return state.builder_draft


@router.get("/api/builder/draft")
def get_draft(state: AppState = Depends(get_app_state)) -> LineSpec:
    return _require_draft(state)


@router.post("/api/builder/draft/stations")
def insert_station(
    req: InsertStationRequest, state: AppState = Depends(get_app_state)
) -> LineSpec:
    draft = _require_draft(state)
    try:
        state.builder_draft = draft.insert_station(req.station, req.after_station_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.builder_draft


@router.delete("/api/builder/draft/stations/{station_id}")
def remove_station(station_id: str, state: AppState = Depends(get_app_state)) -> LineSpec:
    draft = _require_draft(state)
    try:
        state.builder_draft = draft.remove_station(station_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.builder_draft


@router.post("/api/builder/draft/stations/{station_id}/move")
def move_station(
    station_id: str, req: MoveStationRequest, state: AppState = Depends(get_app_state)
) -> LineSpec:
    draft = _require_draft(state)
    try:
        state.builder_draft = _move_station(draft, station_id, req.direction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.builder_draft


@router.post("/api/builder/save")
def save_draft(req: SaveDraftRequest, state: AppState = Depends(get_app_state)) -> dict:
    draft = _require_draft(state)

    filename = req.filename
    if (
        not filename.endswith(".yaml")
        or "/" in filename
        or "\\" in filename
        or ".." in filename
    ):
        raise HTTPException(
            status_code=400,
            detail="filename must be a plain '*.yaml' basename, no path separators",
        )

    state.lines_root.mkdir(parents=True, exist_ok=True)
    target = state.lines_root / filename
    if target.exists():
        raise HTTPException(status_code=409, detail=f"{filename!r} already exists")

    target.write_text(draft.to_yaml(), encoding="utf-8")
    return {"ok": True, "filename": filename}
