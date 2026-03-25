from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Set

from fastapi import WebSocket


class ConnectionManager:
    """Tracks live WebSocket connections and supports broadcasting JSON messages."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    # PUBLIC_INTERFACE
    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a JSON-serializable message to all connected clients."""
        data = json.dumps(message, default=str)
        async with self._lock:
            conns = list(self._connections)
        for ws in conns:
            try:
                await ws.send_text(data)
            except Exception:
                # Drop dead connections
                await self.disconnect(ws)
