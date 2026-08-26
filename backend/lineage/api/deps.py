"""Shared dependency injection: LineSpec, TickEngine, and registries."""

from pathlib import Path

from lineage.config.specs import LineSpec
from lineage.replay.engine import ReplayEngine
from lineage.replay.store import SnapshotHistory
from lineage.replay.ws import ConnectionManager

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LINE_PATH = BACKEND_DIR / "data" / "lines" / "example_42.yaml"
RUNS_ROOT = BACKEND_DIR / "data" / "runs"


class AppState:
    def __init__(self, line: LineSpec | None = None, runs_root: Path = RUNS_ROOT) -> None:
        self.line: LineSpec | None = line
        self.runs_root = runs_root
        self.engine: ReplayEngine | None = None
        self.connection_manager = ConnectionManager()
        self.snapshot_history = SnapshotHistory()


_state: AppState | None = None


def get_app_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState(line=LineSpec.from_yaml(DEFAULT_LINE_PATH))
    return _state


def reset_app_state(state: AppState | None = None) -> None:
    """Test/CLI hook to replace the process-wide singleton."""
    global _state
    _state = state
