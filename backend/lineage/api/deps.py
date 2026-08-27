"""Shared dependency injection: LineSpec, TickEngine, and registries."""

from pathlib import Path

from lineage.act.ledger import AuditLedger
from lineage.act.models import Proposal
from lineage.config.specs import LineSpec
from lineage.predict.ledger import PredictionLedger
from lineage.replay.engine import ReplayEngine
from lineage.replay.store import SnapshotHistory
from lineage.replay.ws import ConnectionManager
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
    ) -> None:
        self.line: LineSpec | None = line
        self.runs_root = runs_root
        self.lines_root = lines_root
        self.models_root = models_root
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
        _state = AppState(line=LineSpec.from_yaml(DEFAULT_LINE_PATH))
    return _state


def reset_app_state(state: AppState | None = None) -> None:
    """Test/CLI hook to replace the process-wide singleton."""
    global _state
    _state = state
