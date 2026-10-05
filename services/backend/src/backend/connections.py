"""Conexiones WebSocket abiertas, agrupadas por cuidador."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # Un cuidador puede tener varias conexiones (móvil y tablet, por ejemplo).
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)

    def add(self, staff_id: str, websocket: WebSocket) -> None:
        self._sockets[staff_id].add(websocket)

    def discard(self, staff_id: str, websocket: WebSocket) -> None:
        sockets = self._sockets.get(staff_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            del self._sockets[staff_id]

    def connected_staff(self) -> list[str]:
        return sorted(self._sockets)

    async def send(self, staff_ids: Iterable[str], message: dict[str, Any]) -> None:
        for staff_id in staff_ids:
            for websocket in list(self._sockets.get(staff_id, ())):
                try:
                    await websocket.send_json(message)
                except Exception:
                    # Una conexión rota no debe impedir que el resto reciba la alerta.
                    logger.warning("websocket_send_failed", extra={"staff_id": staff_id})
                    self.discard(staff_id, websocket)
