"""Tests de la API del backend con un puente MQTT falso (sin red)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from backend.app import WS_UNKNOWN_STAFF, create_app
from backend.mqtt_bridge import BridgeUnavailableError, ClearedHandler, UpdateHandler
from backend.settings import BackendSettings
from fastapi.testclient import TestClient
from residencia_shared.config import SystemConfig
from residencia_shared.events import EventType, Location, Severity, ZoneType, new_id
from residencia_shared.internal import (
    CaregiverAction,
    CaregiverActionType,
    EscalationStage,
    Incident,
    IncidentStatus,
    IncidentUpdate,
    UpdateReason,
)
from starlette.websockets import WebSocketDisconnect

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


class FakeBridge:
    def __init__(self) -> None:
        self.connected = True
        self.actions: list[CaregiverAction] = []

    async def run(self) -> None:
        await asyncio.Event().wait()

    async def publish_action(self, action: CaregiverAction) -> None:
        if not self.connected:
            raise BridgeUnavailableError("down")
        self.actions.append(action)


def make_update(
    version: int = 1,
    *,
    incident_id: str = "inc_a",
    status: IncidentStatus = IncidentStatus.OPEN,
    notified: list[str] | None = None,
    accepted_by: str | None = None,
) -> IncidentUpdate:
    incident = Incident(
        incident_id=incident_id,
        version=version,
        category="fall",
        status=status,
        priority=Severity.CRITICAL,
        location=Location(floor_id="p1", zone_id="hab_12", zone_type=ZoneType.ROOM),
        title="Caída confirmada",
        message="Caída confirmada en Habitación 12 (Planta 1).",
        stage=EscalationStage.ZONE_CAREGIVER,
        stage_started_at=T0,
        notified=notified if notified is not None else ["cuid_d4"],
        accepted_by=accepted_by,
        created_at=T0,
        updated_at=T0,
        last_event_at=T0,
        last_event_type=EventType.FALL_CONFIRMED,
        event_ids=["evt_000001"],
    )
    return IncidentUpdate(
        message_id=new_id("msg"),
        timestamp=T0,
        reason=UpdateReason.CREATED,
        new_recipients=incident.notified,
        incident=incident,
    )


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def client(system_config: SystemConfig, bridge: FakeBridge) -> Iterator[TestClient]:
    def factory(_: UpdateHandler, __: ClearedHandler) -> FakeBridge:
        return bridge

    app = create_app(BackendSettings(), system_config, bridge_factory=factory)
    with TestClient(app) as test_client:
        yield test_client


def push(client: TestClient, update: IncidentUpdate) -> None:
    """Simula la llegada de una actualización del orquestador por MQTT."""
    client.portal.call(client.app.state.handle_update, update)  # type: ignore[attr-defined]


def clear(client: TestClient, incident_id: str) -> None:
    client.portal.call(client.app.state.handle_cleared, incident_id)  # type: ignore[attr-defined]


# --- REST --------------------------------------------------------------------------------


def test_health_reports_bus_state(client: TestClient, bridge: FakeBridge) -> None:
    assert client.get("/health").json() == {"status": "ok", "mqtt_connected": True}
    bridge.connected = False
    assert client.get("/health").json()["mqtt_connected"] is False


def test_lists_active_incidents(client: TestClient) -> None:
    push(client, make_update())
    body = client.get("/incidents").json()
    assert [i["incident_id"] for i in body] == ["inc_a"]
    assert client.get("/incidents/inc_a").json()["priority"] == "critical"
    assert client.get("/incidents/inc_zzz").status_code == 404


def test_accept_forwards_action_to_orchestrator(client: TestClient, bridge: FakeBridge) -> None:
    push(client, make_update())
    response = client.post("/incidents/inc_a/accept", json={"staff_id": "cuid_d4"})
    assert response.status_code == 202
    [action] = bridge.actions
    assert action.incident_id == "inc_a"
    assert action.staff_id == "cuid_d4"
    assert action.action is CaregiverActionType.ACCEPT
    assert response.json()["action_id"] == action.action_id
    # El backend no cambia el estado: eso lo decide y lo publica el orquestador.
    assert client.get("/incidents/inc_a").json()["status"] == "open"


def test_accept_unknown_incident_is_404(client: TestClient, bridge: FakeBridge) -> None:
    response = client.post("/incidents/inc_zzz/accept", json={"staff_id": "cuid_d4"})
    assert response.status_code == 404
    assert bridge.actions == []


def test_accept_by_unknown_staff_is_404(client: TestClient, bridge: FakeBridge) -> None:
    push(client, make_update())
    response = client.post("/incidents/inc_a/accept", json={"staff_id": "intruso"})
    assert response.status_code == 404
    assert bridge.actions == []


def test_accept_already_accepted_incident_is_409(client: TestClient, bridge: FakeBridge) -> None:
    push(client, make_update(status=IncidentStatus.ACCEPTED, accepted_by="cuid_d4"))
    response = client.post("/incidents/inc_a/accept", json={"staff_id": "cuid_d5"})
    assert response.status_code == 409
    assert "cuid_d4" in response.json()["detail"]
    assert bridge.actions == []


def test_resolve_accepted_incident(client: TestClient, bridge: FakeBridge) -> None:
    push(client, make_update(status=IncidentStatus.ACCEPTED, accepted_by="cuid_d4"))
    response = client.post("/incidents/inc_a/resolve", json={"staff_id": "cuid_d4"})
    assert response.status_code == 202
    assert bridge.actions[0].action is CaregiverActionType.RESOLVE


def test_pending_review_incident_can_be_accepted(client: TestClient, bridge: FakeBridge) -> None:
    push(client, make_update(status=IncidentStatus.PENDING_REVIEW))
    response = client.post("/incidents/inc_a/accept", json={"staff_id": "cuid_d4"})
    assert response.status_code == 202
    assert bridge.actions[0].action is CaregiverActionType.ACCEPT
    # Sigue en la lista de activos: un cuidador tiene que revisarlo.
    assert [i["status"] for i in client.get("/incidents").json()] == ["pending_review"]


def test_action_while_bus_is_down_is_503(client: TestClient, bridge: FakeBridge) -> None:
    push(client, make_update())
    bridge.connected = False
    response = client.post("/incidents/inc_a/accept", json={"staff_id": "cuid_d4"})
    assert response.status_code == 503


# --- WebSocket ---------------------------------------------------------------------------


def test_websocket_rejects_unknown_staff(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/ws/intruso"):
        pass
    assert exc.value.code == WS_UNKNOWN_STAFF


def test_websocket_sends_snapshot_of_own_incidents(client: TestClient) -> None:
    push(client, make_update(incident_id="inc_mine", notified=["cuid_d4"]))
    push(client, make_update(incident_id="inc_other", notified=["cuid_d1"]))
    with client.websocket_connect("/ws/cuid_d4") as ws:
        message: dict[str, Any] = ws.receive_json()
    assert message["type"] == "snapshot"
    assert [i["incident_id"] for i in message["data"]] == ["inc_mine"]


def test_websocket_pushes_updates_only_to_the_audience(client: TestClient) -> None:
    with (
        client.websocket_connect("/ws/cuid_d4") as d4,
        client.websocket_connect("/ws/cuid_d5") as d5,
    ):
        assert d4.receive_json()["data"] == []
        assert d5.receive_json()["data"] == []

        push(client, make_update(1, notified=["cuid_d4"]))
        first = d4.receive_json()
        assert first["type"] == "incident_update"
        assert first["data"]["incident"]["version"] == 1

        # Escala a la planta: ahora también le llega a cuid_d5.
        push(client, make_update(2, notified=["cuid_d4", "cuid_d5"]))
        assert d4.receive_json()["data"]["incident"]["version"] == 2
        assert d5.receive_json()["data"]["incident"]["version"] == 2


def test_websocket_ignores_stale_updates(client: TestClient) -> None:
    push(client, make_update(2))
    with client.websocket_connect("/ws/cuid_d4") as ws:
        ws.receive_json()  # snapshot
        push(client, make_update(1))  # antiguo: no se reenvía
        push(client, make_update(3))
        assert ws.receive_json()["data"]["incident"]["version"] == 3


def test_websocket_notifies_removed_incident(client: TestClient) -> None:
    push(client, make_update())
    with client.websocket_connect("/ws/cuid_d4") as ws:
        ws.receive_json()  # snapshot
        clear(client, "inc_a")
        message = ws.receive_json()
    assert message == {"type": "incident_removed", "data": {"incident_id": "inc_a"}}
    assert client.get("/incidents").json() == []
