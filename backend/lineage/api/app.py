"""FastAPI app factory."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lineage.api.deps import DEFAULT_LINE_PATH, RUNS_ROOT, get_app_state
from lineage.api.routes.act import router as act_router
from lineage.api.routes.builder import router as builder_router
from lineage.api.routes.datagen import router as datagen_router
from lineage.api.routes.line import router as line_router
from lineage.api.routes.mirror import router as mirror_router
from lineage.api.routes.predict import router as predict_router
from lineage.api.routes.trace import router as trace_router
from lineage.api.routes.views import router as views_router
from lineage.config.loader import load_line_spec
from lineage.datagen.cli import build_default_run_config
from lineage.datagen.run import generate_run
from lineage.replay.models import PlaybackMode

TICK_INTERVAL_REAL_S = 1.0
DEFAULT_RUN_ID = "default_400_car_run"


def _ensure_default_run_exists() -> None:
    """Render's filesystem doesn't persist between deploys, so this is a
    cheap safety net, not the primary path -- default_400_car_run is
    committed to the repo (regenerating it measured ~5s, confirmed) precisely
    so this almost never has to do anything. Training a risk model is
    deliberately NOT attempted here even if missing: it takes several
    minutes (see README's Known limitations), nowhere near boot-safe -- a
    missing model just leaves the prediction ledger unavailable, exactly
    the existing graceful 409 behaviour in api/routes/predict.py."""
    if (RUNS_ROOT / DEFAULT_RUN_ID).exists():
        return
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)
    generate_run(line, config, RUNS_ROOT)


async def _tick_loop() -> None:
    while True:
        await asyncio.sleep(TICK_INTERVAL_REAL_S)
        try:
            state = get_app_state()
            if state.engine is None:
                continue
            if state.engine.clock.mode == PlaybackMode.PAUSED:
                continue
            # engine.tick() re-scans run data and measurably grows to
            # seconds late in a run (see README's Known limitations) --
            # run it in a worker thread so a slow tick never blocks the
            # event loop that serves every request and WebSocket send.
            line_state = await asyncio.to_thread(state.engine.tick)
            state.snapshot_history.push(line_state)
            await state.connection_manager.broadcast(line_state)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One bad tick must never silently kill the loop -- that would
            # freeze the live view for the rest of the process's life.
            logging.getLogger(__name__).exception("tick loop iteration failed; continuing")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _ensure_default_run_exists()
    task = asyncio.create_task(_tick_loop())
    try:
        yield
    finally:
        task.cancel()


def _allowed_origins() -> list[str]:
    """ALLOWED_ORIGIN is set in deployment (Render) to the real Vercel
    origin; unset locally, where the Vite dev server on :5173 is the only
    origin that ever needs it. Comma-separated for more than one origin
    (e.g. a preview deployment alongside production)."""
    configured = os.environ.get("ALLOWED_ORIGIN")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return ["http://localhost:5173"]


def create_app() -> FastAPI:
    app = FastAPI(lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(line_router)
    app.include_router(mirror_router)
    app.include_router(views_router)
    app.include_router(builder_router)
    app.include_router(predict_router)
    app.include_router(trace_router)
    app.include_router(act_router)
    app.include_router(datagen_router)
    return app


app = create_app()
