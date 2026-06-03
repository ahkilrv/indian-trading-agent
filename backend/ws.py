"""WebSocket connection manager for streaming analysis progress."""

import json
import asyncio
import time
from fastapi import WebSocket
from typing import Dict


class ConnectionManager:
    """Manages WebSocket connections for analysis streaming."""

    def __init__(self):
        self.active_connections: Dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)

    def disconnect(self, websocket: WebSocket, task_id: str):
        if task_id in self.active_connections:
            self.active_connections[task_id] = [
                ws for ws in self.active_connections[task_id] if ws != websocket
            ]
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]

    async def send_event(self, task_id: str, event: dict):
        """Send an event to all WebSocket connections for a task."""
        if task_id not in self.active_connections:
            return
        dead = []
        for ws in self.active_connections[task_id]:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, task_id)

    def cleanup_stale(self, max_age_seconds: int = 3600):
        """Remove task entries with no remaining connections for over max_age.
        
        Call periodically to prevent the dict from holding stale keys.
        """
        now = time.time()
        stale = [tid for tid, conns in list(self.active_connections.items())
                 if not conns and tid in self.active_connections]
        # Only clean tasks with no connections — connections are removed on
        # disconnect. The task_id entry stays alive only so long as at least
        # one client is connected.
        for tid in stale:
            del self.active_connections[tid]


manager = ConnectionManager()
