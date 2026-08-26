"""In-memory ring buffer of recent ticks per station, for history and late-joining clients."""

from collections import deque

from lineage.replay.models import LineState


class SnapshotHistory:
    def __init__(self, maxlen: int = 50) -> None:
        self._buffer: deque[LineState] = deque(maxlen=maxlen)

    def push(self, state: LineState) -> None:
        self._buffer.append(state)

    def recent(self) -> list[LineState]:
        return list(self._buffer)
