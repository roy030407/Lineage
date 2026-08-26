"""FastAPI app factory."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lineage.api.deps import get_app_state
from lineage.api.routes.line import router as line_router
from lineage.api.routes.mirror import router as mirror_router
from lineage.replay.models import PlaybackMode

TICK_INTERVAL_REAL_S = 1.0


async def _tick_loop() -> None:
    while True:
        await asyncio.sleep(TICK_INTERVAL_REAL_S)
        state = get_app_state()
        if state.engine is None:
            continue
        if state.engine.clock.mode == PlaybackMode.PAUSED:
            continue
        line_state = state.engine.tick()
        state.snapshot_history.push(line_state)
        await state.connection_manager.broadcast(line_state)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    task = asyncio.create_task(_tick_loop())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=_lifespan)
    app.include_router(line_router)
    app.include_router(mirror_router)
    return app


app = create_app()
