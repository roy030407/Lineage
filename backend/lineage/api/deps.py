"""Shared dependency injection: LineSpec, TickEngine, and registries."""

import threading
from pathlib import Path

from lineage.act.ledger import AuditLedger
from lineage.act.models import Proposal
from lineage.config.specs import LineSpec
from lineage.predict.ledger import PredictionLedger
from lineage.replay.engine import ReplayEngine
from lineage.replay.store import SnapshotHistory
from lineage.replay.ws import ConnectionManager
from lineage.trace.models import TraceResult
from lineage.twin.genealogy import GenealogyStore

BACKEND_DIR = Path(__file__).resolve().parents[2]
LINES_ROOT = BACKEND_DIR / "data" / "lines"
DEFAULT_LINE_PATH = LINES_ROOT / "example_42.yaml"
RUNS_ROOT = BACKEND_DIR / "data" / "runs"
MODELS_ROOT = BACKEND_DIR / "data" / "models"
DEFAULT_RISK_MODEL_DIR = MODELS_ROOT / "risk_v1"


class AppState:
    def __init__(
        self,
        line: LineSpec | None = None,
        runs_root: Path = RUNS_ROOT,
        lines_root: Path = LINES_ROOT,
        models_root: Path = MODELS_ROOT,
        autoload_default_run: bool = False,
    ) -> None:
        self.line: LineSpec | None = line
        self.runs_root = runs_root
        self.lines_root = lines_root
        self.models_root = models_root
        self.autoload_default_run = autoload_default_run
        """Whether api/app.py's lifespan should load DEFAULT_RUN_ID at boot
        so the Mirror opens on a live line instead of an empty canvas.

        Defaults to False, and only get_app_state() below sets it True, so
        this is opt-in for the shipped configuration alone. That default is
        load-bearing: any state constructed directly (every test, every CLI
        entry point) has substituted at least one of line/runs_root, and a
        run is only ever valid against the line it was generated from.

        An earlier attempt guarded on "does DEFAULT_RUN_ID exist under
        state.runs_root" instead. That is the wrong question and it broke
        26 tests: tests/unit/test_api_builder.py substitutes `line` but
        leaves runs_root at the real RUNS_ROOT, which does contain the
        committed 42-station default run, so the autoload tried to build a
        genealogy store for 42 stations against a 3-station line and died
        with KeyError: 'ST-04'. Existence of a run says nothing about
        whether it matches the loaded line."""
        self.engine: ReplayEngine | None = None
        self.connection_manager = ConnectionManager()
        self.snapshot_history = SnapshotHistory()
        self.genealogy_store: GenealogyStore | None = None
        """Built once via twin.ingest.from_generated_run when a run is
        loaded (see api/routes/mirror.py's "load" action); car-history
        queries read from this cache, they never rebuild it per request."""
        self.builder_draft: LineSpec | None = None
        """A LineSpec being edited by the builder, independent of `line` --
        editing a draft never disturbs a Mirror session using the loaded
        line for replay. See api/routes/builder.py."""
        self.current_run_dir: Path | None = None
        """Set at 'load' time so the prediction ledger can be built lazily
        (see prediction_ledger below) without mirror.py's load action having
        to know anything about predict/."""
        self.prediction_ledger: PredictionLedger | None = None
        """Built lazily on first request to /api/predict/*, then cached here
        -- NOT built eagerly at 'load' time. Assessing every car in a run
        against every inspection station it reached is real, non-trivial
        work (observed: ~105s for a 400-car run), and 'load' is expected to
        stay fast, matching genealogy_store's much cheaper build. Reset to
        None on every new 'load' so a stale run's ledger is never served.
        Also None whenever no trained risk model is found -- data/models/ is
        gitignored (a locally-trained artifact, not committed), so a fresh
        clone or CI environment legitimately has none. See
        api/routes/predict.py."""
        self.prediction_ledger_lock = threading.Lock()
        """Guards the lazy build above. FastAPI runs sync `def` route
        handlers in a real OS thread pool, not as coroutines on one event
        loop, so a plain `if state.prediction_ledger is None: build it`
        check is a genuine race: the frontend's 5s poll can (and did, in
        practice) land a second request before the ~105s first build
        finishes, starting an entirely redundant second build rather than
        waiting for the first. A `threading.Lock` (not `asyncio.Lock`,
        which isn't safe across real threads) plus a re-check of
        `prediction_ledger` after acquiring it (double-checked locking) means
        only the first request actually builds; every other concurrent
        request blocks on the lock and then returns the same already-built
        ledger instead of starting its own."""
        self.trace_results: list[TraceResult] | None = None
        """Every real failed inspection in the run, traced back to its likely
        origin -- built lazily on whichever of Act's proposal listing or
        Plant Manager's recurring-root-cause report is requested first, then
        shared by both (see trace.lineage_query.traced_failures), since
        tracing every failure is real per-car work, not free, and both
        features need the exact same computation. Reset to None on every new
        'load'."""
        self.act_proposals: list[Proposal] | None = None
        """Built lazily on first request to GET /api/act/proposals, then
        cached here (same reasoning as prediction_ledger: real per-car Trace
        work, not free) so approving one by id later in the same loaded run
        finds the same object, not a freshly regenerated uuid. Reset to None
        on every new 'load'. See api/routes/act.py."""
        self.audit_ledger = AuditLedger()
        """Append-only record of every Act proposal decision. NOT reset on a
        new 'load' -- unlike the caches above, an audit trail of what was
        actually approved is exactly the kind of thing that should survive
        switching runs, not be silently dropped."""
        self.issue_assignments: dict[str, str] = {}
        """issue_id (a station_id or car_id from the Floor Supervisor alert
        queue) -> operator_id. A minimal, in-memory assignment record, not a
        real auth/session system -- there is no live operator login in this
        prototype, so operator_id is whatever the floor supervisor types
        (typically one of datagen's OP-{station}-A/B ids). Reset on a new
        'load', same as the caches above: an assignment refers to a specific
        run's alert, which no longer exists once that run is gone."""


_state: AppState | None = None
"""A bare process-wide Python global. This app can only ever run as a
single process/worker -- api/app.py's background tick loop only advances
state on whatever process has an engine loaded, and a second worker gets
its own separate, empty copy of this global with no way to share it. If
'load' lands on one process and a live request (especially the WebSocket)
lands on another, the second process just sits forever on its own initial
state, showing whatever was true at the moment it started -- this was a
real, diagnosed symptom (see NOTES-OVERNIGHT.md), not a hypothetical.
render.yaml pins --workers 1 explicitly for exactly this reason. Scaling
beyond one process/instance requires moving this out of an in-process
global first (Redis or similar), not just raising a number."""


def get_app_state() -> AppState:
    global _state
    if _state is None:
        # The only place autoload_default_run is ever True: this is the
        # shipped configuration, the default line paired with the default
        # runs root, which is exactly the pairing the default run is valid
        # against.
        _state = AppState(
            line=LineSpec.from_yaml(DEFAULT_LINE_PATH), autoload_default_run=True
        )
    return _state


def reset_app_state(state: AppState | None = None) -> None:
    """Test/CLI hook to replace the process-wide singleton."""
    global _state
    _state = state
