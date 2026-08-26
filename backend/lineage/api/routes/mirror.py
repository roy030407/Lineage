"""Live state REST endpoints and the WebSocket upgrade route."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from lineage.api.deps import AppState, get_app_state
from lineage.replay.engine import ReplayEngine
from lineage.replay.run_data import RunData

router = APIRouter()


@router.get("/api/runs")
def list_runs(state: AppState = Depends(get_app_state)) -> list[dict]:
    if not state.runs_root.exists():
        return []
    return [{"run_id": p.name} for p in sorted(state.runs_root.iterdir()) if p.is_dir()]


class ReplayControlRequest(BaseModel):
    action: Literal["load", "play", "pause", "step", "seek", "set_speed"]
    run_id: str | None = None
    timestamp: datetime | None = None
    speed_multiplier: float | None = None


@router.post("/api/replay/control")
def replay_control(req: ReplayControlRequest, state: AppState = Depends(get_app_state)) -> dict:
    if req.action == "load":
        if req.run_id is None:
            raise HTTPException(status_code=400, detail="run_id required for 'load'")
        if state.line is None:
            raise HTTPException(status_code=404, detail="no line loaded")
        run_dir = state.runs_root / req.run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail=f"unknown run {req.run_id!r}")
        run_data = RunData(req.run_id, run_dir)
        state.engine = ReplayEngine(state.line, run_data, start_time=run_data.start_time)
        return {"ok": True}

    if state.engine is None:
        raise HTTPException(status_code=409, detail="no run loaded; send action='load' first")

    if req.action == "play":
        state.engine.resume()
    elif req.action == "pause":
        state.engine.pause()
    elif req.action == "step":
        state.engine.set_step_mode()
        state.engine.step()
    elif req.action == "seek":
        if req.timestamp is None:
            raise HTTPException(status_code=400, detail="timestamp required for 'seek'")
        state.engine.seek(req.timestamp)
    elif req.action == "set_speed":
        if req.speed_multiplier is None:
            raise HTTPException(status_code=400, detail="speed_multiplier required for 'set_speed'")
        state.engine.set_speed(req.speed_multiplier)

    return {"ok": True}


@router.websocket("/ws/line")
async def ws_line(websocket: WebSocket, state: AppState = Depends(get_app_state)) -> None:
    await state.connection_manager.connect(websocket)
    for snapshot in state.snapshot_history.recent():
        await websocket.send_json(snapshot.model_dump(mode="json"))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.connection_manager.disconnect(websocket)
