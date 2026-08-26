"""WebSocket connection manager and broadcaster for live tick frames."""

from fastapi import WebSocket

from lineage.replay.models import LineState


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, state: LineState) -> None:
        data = state.model_dump(mode="json")
        for websocket in list(self._connections):
            try:
                await websocket.send_json(data)
            except Exception:
                self.disconnect(websocket)
