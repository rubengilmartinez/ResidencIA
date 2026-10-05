"""Puente entre el backend y el bus MQTT interno.

- Recibe el estado de los incidentes desde ``sistema/alertas/+`` (mensajes retenidos: al
  conectarse recibe el estado completo de los incidentes activos).
- Publica las acciones de los cuidadores en ``sistema/acciones``.

La sesión es persistente (``clean_session=False``): si el backend pierde la conexión un
momento, el broker le guarda los cambios intermedios, incluida la resolución de un
incidente cuyo retenido ya se ha borrado.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

import aiomqtt
from residencia_shared.internal import CaregiverAction, IncidentUpdate
from residencia_shared.topics import ACTIONS_TOPIC, ALERTS_SUBSCRIPTION, parse_alert_topic

logger = logging.getLogger(__name__)

UpdateHandler = Callable[[IncidentUpdate], Awaitable[None]]
ClearedHandler = Callable[[str], Awaitable[None]]

MAX_BACKOFF_S = 30.0


class BridgeUnavailableError(Exception):
    """No hay conexión con el bus; la acción no se ha podido enviar."""


class Bridge(Protocol):
    @property
    def connected(self) -> bool: ...
    async def run(self) -> None: ...
    async def publish_action(self, action: CaregiverAction) -> None: ...


class MqttBridge:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: str,
        on_update: UpdateHandler,
        on_cleared: ClearedHandler,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._on_update = on_update
        self._on_cleared = on_cleared
        self._client: aiomqtt.Client | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self._host,
                    port=self._port,
                    identifier=self._client_id,
                    clean_session=False,
                ) as client:
                    await client.subscribe(ALERTS_SUBSCRIPTION, qos=1)
                    # Solo se considera conectado cuando ya está suscrito.
                    self._client = client
                    backoff = 1.0
                    logger.info("mqtt_connected", extra={"host": self._host})
                    async for message in client.messages:
                        await self._handle(message)
            except aiomqtt.MqttError as exc:
                logger.warning(
                    "mqtt_disconnected", extra={"error": str(exc), "retry_in_s": backoff}
                )
            finally:
                self._client = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)

    async def _handle(self, message: aiomqtt.Message) -> None:
        topic = message.topic.value
        payload = message.payload
        try:
            incident_id = parse_alert_topic(topic)
            if not payload:
                await self._on_cleared(incident_id)
                return
            if not isinstance(payload, bytes | bytearray | str):
                raise ValueError(f"unexpected payload type {type(payload).__name__}")
            update = IncidentUpdate.model_validate_json(payload)
            if update.incident.incident_id != incident_id:
                raise ValueError("incident id does not match topic")
            await self._on_update(update)
        except ValueError as exc:
            logger.warning("alert_message_rejected", extra={"topic": topic, "error": str(exc)})
        except Exception:
            logger.exception("alert_message_failed", extra={"topic": topic})

    async def publish_action(self, action: CaregiverAction) -> None:
        client = self._client
        if client is None:
            raise BridgeUnavailableError("not connected to MQTT")
        try:
            await client.publish(ACTIONS_TOPIC, action.model_dump_json(), qos=1)
        except aiomqtt.MqttError as exc:
            raise BridgeUnavailableError(str(exc)) from exc
