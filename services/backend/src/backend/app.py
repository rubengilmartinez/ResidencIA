"""API del backend.

- ``WS /ws/{staff_id}``: al conectarse, el cuidador recibe sus incidentes activos
  (``snapshot``) y después cada cambio (``incident_update``, ``incident_removed``).
  El cliente debe quedarse con la versión más alta de cada incidente.
- ``POST /incidents/{id}/accept`` y ``/resolve``: envían la acción al orquestador y
  responden 202. El resultado llega por WebSocket, porque quien decide es el orquestador
  (si dos cuidadores aceptan a la vez, gana el primero que procesa).

Limitación conocida: no hay autenticación. El ``staff_id`` se confía al cliente; antes de
cualquier despliegue real hace falta autenticar a los cuidadores.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from residencia_shared.config import SystemConfig
from residencia_shared.events import new_id, utc_now
from residencia_shared.internal import (
    CaregiverAction,
    CaregiverActionType,
    Incident,
    IncidentStatus,
    IncidentUpdate,
)

from backend.board import IncidentBoard
from backend.connections import ConnectionManager
from backend.mqtt_bridge import (
    Bridge,
    BridgeUnavailableError,
    ClearedHandler,
    MqttBridge,
    UpdateHandler,
)
from backend.settings import BackendSettings

logger = logging.getLogger(__name__)

BridgeFactory = Callable[[UpdateHandler, ClearedHandler], Bridge]

# Código de cierre para cuidadores desconocidos (rango 4000-4999 reservado a aplicaciones).
WS_UNKNOWN_STAFF = 4404


class HealthResponse(BaseModel):
    status: str
    mqtt_connected: bool


class ActionRequest(BaseModel):
    staff_id: str


class ActionSubmitted(BaseModel):
    action_id: str
    incident_id: str
    action: CaregiverActionType


def create_app(
    settings: BackendSettings,
    config: SystemConfig,
    bridge_factory: BridgeFactory | None = None,
) -> FastAPI:
    board = IncidentBoard()
    connections = ConnectionManager()

    async def handle_update(update: IncidentUpdate) -> None:
        if not board.apply(update):
            return
        await connections.send(
            board.audience(update.incident),
            {"type": "incident_update", "data": update.model_dump(mode="json")},
        )

    async def handle_cleared(incident_id: str) -> None:
        removed = board.remove(incident_id)
        if removed is not None:
            await connections.send(
                board.audience(removed),
                {"type": "incident_removed", "data": {"incident_id": incident_id}},
            )

    if bridge_factory is None:
        bridge: Bridge = MqttBridge(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            client_id=settings.mqtt_client_id,
            on_update=handle_update,
            on_cleared=handle_cleared,
        )
    else:
        bridge = bridge_factory(handle_update, handle_cleared)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(bridge.run())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="ResidencIA backend", version="0.1.0", lifespan=lifespan)
    app.state.board = board
    app.state.bridge = bridge
    app.state.handle_update = handle_update
    app.state.handle_cleared = handle_cleared

    @app.get("/health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", mqtt_connected=bridge.connected)

    @app.get("/incidents")
    async def list_incidents() -> list[Incident]:
        return board.active()

    @app.get("/incidents/{incident_id}")
    async def get_incident(incident_id: str) -> Incident:
        incident = board.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="unknown incident")
        return incident

    @app.get("/staff/{staff_id}/incidents")
    async def staff_incidents(staff_id: str) -> list[Incident]:
        _require_staff(staff_id)
        return board.active_for(staff_id)

    @app.post("/incidents/{incident_id}/accept", status_code=202)
    async def accept(incident_id: str, body: ActionRequest) -> ActionSubmitted:
        return await _submit(incident_id, body.staff_id, CaregiverActionType.ACCEPT)

    @app.post("/incidents/{incident_id}/resolve", status_code=202)
    async def resolve(incident_id: str, body: ActionRequest) -> ActionSubmitted:
        return await _submit(incident_id, body.staff_id, CaregiverActionType.RESOLVE)

    @app.websocket("/ws/{staff_id}")
    async def staff_socket(websocket: WebSocket, staff_id: str) -> None:
        if config.staff_member(staff_id) is None:
            await websocket.close(code=WS_UNKNOWN_STAFF)
            return
        await websocket.accept()
        connections.add(staff_id, websocket)
        logger.info("websocket_connected", extra={"staff_id": staff_id})
        try:
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "data": [i.model_dump(mode="json") for i in board.active_for(staff_id)],
                }
            )
            while True:
                # Por ahora el cliente no envía nada; esto mantiene la conexión abierta.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            connections.discard(staff_id, websocket)
            logger.info("websocket_disconnected", extra={"staff_id": staff_id})

    def _require_staff(staff_id: str) -> None:
        if config.staff_member(staff_id) is None:
            raise HTTPException(status_code=404, detail="unknown staff member")

    async def _submit(
        incident_id: str, staff_id: str, kind: CaregiverActionType
    ) -> ActionSubmitted:
        _require_staff(staff_id)
        incident = board.get(incident_id)
        if incident is None or incident.status is IncidentStatus.RESOLVED:
            raise HTTPException(status_code=404, detail="unknown or resolved incident")
        # Se puede aceptar un incidente abierto o pendiente de revisión (falsa alarma).
        if kind is CaregiverActionType.ACCEPT and incident.status is IncidentStatus.ACCEPTED:
            raise HTTPException(
                status_code=409, detail=f"incident already accepted by {incident.accepted_by}"
            )
        action = CaregiverAction(
            action_id=new_id("act"),
            timestamp=utc_now(),
            incident_id=incident_id,
            staff_id=staff_id,
            action=kind,
        )
        try:
            await bridge.publish_action(action)
        except BridgeUnavailableError as exc:
            logger.warning("action_not_sent", extra={"action_id": action.action_id})
            raise HTTPException(status_code=503, detail="message bus unavailable") from exc
        logger.info(
            "action_submitted",
            extra={
                "action_id": action.action_id,
                "incident_id": incident_id,
                "staff_id": staff_id,
                "action": kind.value,
            },
        )
        return ActionSubmitted(action_id=action.action_id, incident_id=incident_id, action=kind)

    return app
