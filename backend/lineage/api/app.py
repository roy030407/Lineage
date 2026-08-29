"""FastAPI app factory."""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lineage.api.deps import DEFAULT_LINE_PATH, RUNS_ROOT, get_app_state
from lineage.api.routes.act import router as act_router
from lineage.api.routes.builder import router as builder_router
from lineage.api.routes.datagen import router as datagen_router
from lineage.api.routes.line import router as line_router
from lineage.api.routes.mirror import load_run_into_state
from lineage.api.routes.mirror import router as mirror_router
from lineage.api.routes.predict import router as predict_router
from lineage.api.routes.views import router as views_router
from lineage.api.security import api_key_middleware
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


def _autoload_default_run() -> None:
    """Opens the Mirror on a live line rather than an empty canvas.

    Gated on state.autoload_default_run, which only api/deps.py's
    get_app_state() ever sets True. Any AppState built directly has
    substituted the line, the runs root, or both, and a generated run is
    only valid against the line it came from. See that flag's docstring for
    the 26-test failure that established this.

    The existence check behind the flag is defence in depth: a missing
    default run must leave the engine unloaded, not raise inside lifespan
    and take the whole app down at boot.

    Reuses load_run_into_state verbatim; no second load path exists.
    """
    state = get_app_state()
    if not state.autoload_default_run:
        return
    if state.line is None:
        return
    if not (state.runs_root / DEFAULT_RUN_ID).exists():
        return
    load_run_into_state(state, DEFAULT_RUN_ID)


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
    _ensure_default_run_exists()
    _autoload_default_run()
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
    # Registered after CORS so it sits outside it. OPTIONS is exempt inside
    # the middleware itself, so preflight still reaches CORSMiddleware, and
    # allow_headers=["*"] above already admits X-Lineage-Key.
    app.middleware("http")(api_key_middleware)
    app.include_router(line_router)
    app.include_router(mirror_router)
    app.include_router(views_router)
    app.include_router(builder_router)
    app.include_router(predict_router)
    app.include_router(act_router)
    app.include_router(datagen_router)
    return app


app = create_app()
