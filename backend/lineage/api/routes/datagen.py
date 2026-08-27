"""On-demand fresh-run generation: the "Simulate" button's backend.

Reuses build_run_config's exact scenario shape (the same defect seeds and
operator setup as the committed default_400_car_run) with a fresh random
seed, today's start time, and a unique run_id, then loads it through the
same path action='load' already uses -- no new load logic, and the frozen
default_400_car_run fixture is never touched by this endpoint.
"""

import random
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lineage.api.deps import AppState, get_app_state
from lineage.api.routes.mirror import load_run_into_state
from lineage.datagen.cli import build_run_config
from lineage.datagen.run import generate_run

router = APIRouter()


class SimulateResponse(BaseModel):
    run_id: str
    num_cars: int


@router.post("/api/datagen/simulate")
def simulate(state: AppState = Depends(get_app_state)) -> SimulateResponse:
    if state.line is None:
        raise HTTPException(status_code=404, detail="no line loaded")

    run_id = f"simulated_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    config = build_run_config(
        state.line,
        run_id=run_id,
        random_seed=random.randint(1, 2**31 - 1),
        sim_start_time=datetime.now(),
    )
    artifacts = generate_run(state.line, config, state.runs_root)
    load_run_into_state(state, artifacts.run_id)
    return SimulateResponse(run_id=artifacts.run_id, num_cars=artifacts.num_cars)
