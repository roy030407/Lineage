"""Station builder: edit a draft LineSpec (insert/remove/reorder stations)
and save it as a new line file. Operates on AppState.builder_draft, a
LineSpec independent of whatever `state.line` a Mirror session has loaded
for replay -- editing never disturbs a running session.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from lineage.api.deps import AppState, get_app_state
from lineage.config.commissioning import DEFAULT_SAMPLE_COUNT
from lineage.config.commissioning import run_to_learn as _run_to_learn
from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    EnvironmentEnvelope,
    LineSpec,
    SensorSpec,
    StationSpec,
)
from lineage.replay.store import SnapshotHistory

router = APIRouter()


def _require_draft(state: AppState) -> LineSpec:
    if state.builder_draft is None:
        raise HTTPException(
            status_code=409, detail="no draft started; POST /api/builder/draft/start first"
        )
    return state.builder_draft


def _move_station(line: LineSpec, station_id: str, direction: Literal["up", "down"]) -> LineSpec:
    """Reorders by removing and reinserting the station via the existing,
    already-tested insert_station/remove_station/prepend_station -- rewriting
    conveyor segment topology by hand here would just be a worse
    reimplementation of what those already do correctly.

    Moving into the very first position uses prepend_station, which needs at
    least 2 stations left behind to extrapolate a layout direction from --
    that only fails on lines too small to have a "direction" at all."""
    ids = [s.id for s in line.stations]
    if station_id not in ids:
        raise ValueError(f"unknown station_id {station_id!r}")
    idx = ids.index(station_id)

    if direction == "up":
        if idx == 0:
            raise ValueError("cannot move this station further up: it is already first")
        if idx == 1:
            station = next(s for s in line.stations if s.id == station_id)
            without = line.remove_station(station_id)
            if len(without.stations) < 2:
                raise ValueError(
                    "cannot move this station to the first position: prepend_station "
                    "needs at least 2 remaining stations to extrapolate a layout direction"
                )
            return without.prepend_station(station)
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


class PrependStationRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station: StationSpec


class MoveStationRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    direction: Literal["up", "down"]


class UpdateSensorsRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    sensors: list[SensorSpec]
    acquisition_mode: AcquisitionMode


class UpdateBaselineRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    baseline: CommissioningBaseline | None


class UpdateDistanceRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    from_station_id: str
    to_station_id: str
    distance_m: float


class RunToLearnRequest(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    accuracy_classes: dict[str, str]
    """Quantity name -> accuracy_class string, e.g. {"torque_nm": "1.0"}."""
    idle_nominal: dict[str, float]
    loaded_nominal: dict[str, float]
    sample_count: int = DEFAULT_SAMPLE_COUNT
    seed: int | None = None


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


@router.post("/api/builder/draft/stations/prepend")
def prepend_station(
    req: PrependStationRequest, state: AppState = Depends(get_app_state)
) -> LineSpec:
    draft = _require_draft(state)
    try:
        state.builder_draft = draft.prepend_station(req.station)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.builder_draft


def _station_or_404(line: LineSpec, station_id: str) -> StationSpec:
    station = next((s for s in line.stations if s.id == station_id), None)
    if station is None:
        raise HTTPException(status_code=404, detail=f"unknown station_id {station_id!r}")
    return station


@router.put("/api/builder/draft/stations/{station_id}/sensors")
def update_sensors(
    station_id: str, req: UpdateSensorsRequest, state: AppState = Depends(get_app_state)
) -> LineSpec:
    draft = _require_draft(state)
    current = _station_or_404(draft, station_id)
    try:
        updated = StationSpec(
            **{
                **current.model_dump(),
                "sensors": req.sensors,
                "acquisition_mode": req.acquisition_mode,
            }
        )
        state.builder_draft = draft.replace_station(station_id, updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.builder_draft


@router.put("/api/builder/draft/stations/{station_id}/commissioning_baseline")
def update_baseline(
    station_id: str, req: UpdateBaselineRequest, state: AppState = Depends(get_app_state)
) -> LineSpec:
    draft = _require_draft(state)
    current = _station_or_404(draft, station_id)
    try:
        updated = StationSpec(
            **{**current.model_dump(), "commissioning_baseline": req.baseline}
        )
        state.builder_draft = draft.replace_station(station_id, updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.builder_draft


@router.put("/api/builder/draft/segments/distance")
def update_distance(
    req: UpdateDistanceRequest, state: AppState = Depends(get_app_state)
) -> LineSpec:
    draft = _require_draft(state)
    try:
        state.builder_draft = draft.set_segment_distance(
            req.from_station_id, req.to_station_id, req.distance_m
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.builder_draft


@router.put("/api/builder/draft/environment_envelope")
def update_environment_envelope(
    req: EnvironmentEnvelope, state: AppState = Depends(get_app_state)
) -> LineSpec:
    draft = _require_draft(state)
    state.builder_draft = draft.with_environment_envelope(req)
    return state.builder_draft


@router.post("/api/builder/commissioning/run_to_learn")
def run_to_learn(req: RunToLearnRequest) -> CommissioningBaseline:
    """Standalone simulation, independent of any draft: draws real random
    samples around the given idle/loaded nominal centers, sized by each
    quantity's own accuracy_class, and returns the resulting baseline's
    genuinely-computed mean/std -- see lineage.config.commissioning for why
    this isn't a fabricated number."""
    if set(req.idle_nominal) != set(req.loaded_nominal):
        raise HTTPException(
            status_code=400,
            detail="idle_nominal and loaded_nominal must cover the same quantities",
        )
    try:
        accuracy_fractions = {
            quantity: float(accuracy_class) / 100.0
            for quantity, accuracy_class in req.accuracy_classes.items()
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid accuracy_class: {exc}"
        ) from exc
    return _run_to_learn(
        accuracy_fractions=accuracy_fractions,
        idle_nominal=req.idle_nominal,
        loaded_nominal=req.loaded_nominal,
        sample_count=req.sample_count,
        seed=req.seed,
    )


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


@router.post("/api/builder/activate")
def activate_draft(state: AppState = Depends(get_app_state)) -> LineSpec:
    """Swaps the just-saved draft in as `state.line`, the Mirror's actual
    live line -- the same reset mirror.py's own 'load' action does when
    swapping runs, since every one of these caches was built against the
    *previous* line's stations and is meaningless against the new one.
    audit_ledger is deliberately left alone, same as 'load': it's a record
    of what was actually approved, not tied to which line is live."""
    draft = _require_draft(state)
    state.line = draft
    state.engine = None
    state.genealogy_store = None
    state.current_run_dir = None
    state.prediction_ledger = None
    state.trace_results = None
    state.act_proposals = None
    state.issue_assignments = {}
    state.snapshot_history = SnapshotHistory()
    return state.line
