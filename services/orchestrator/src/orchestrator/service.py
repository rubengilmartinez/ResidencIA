"""Servicio del orquestador: conecta el motor de incidentes con MQTT y la base de datos.

Flujo:
- Suscrito a ``residencia/+/+/+`` (eventos) y ``sistema/acciones`` (acciones de cuidadores).
- Cada evento o acción pasa por el motor; los cambios resultantes se persisten y se
  publican en ``sistema/alertas/{incident_id}`` como mensajes retenidos.
- Un bucle periódico (``tick``) hace avanzar el escalado.

Robustez:
- Sesión MQTT persistente con QoS 1: si el orquestador cae, el broker guarda los eventos
  hasta que vuelve.
- Al arrancar recupera los incidentes abiertos de la base de datos y republica su estado.
- Si falla la base de datos, las alertas se publican igualmente: avisar a un cuidador
  tiene prioridad sobre dejar constancia en el historial.
- Un mensaje mal formado o un error inesperado al procesarlo se registra y se descarta;
  no tumba el servicio.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiomqtt
from residencia_shared.config import SystemConfig
from residencia_shared.events import Event, utc_now
from residencia_shared.internal import CaregiverAction, IncidentStatus, IncidentUpdate
from residencia_shared.topics import (
    ACTIONS_TOPIC,
    EVENTS_SUBSCRIPTION,
    alert_topic,
    check_event_matches_topic,
)

from orchestrator.engine import ActionRejectedError, EventRejectedError, IncidentEngine
from orchestrator.settings import OrchestratorSettings
from orchestrator.store import IncidentStore

logger = logging.getLogger(__name__)

MAX_BACKOFF_S = 30.0


class OrchestratorService:
    def __init__(
        self, settings: OrchestratorSettings, config: SystemConfig, store: IncidentStore
    ) -> None:
        self._settings = settings
        self._config = config
        self._store = store
        self._engine: IncidentEngine | None = None
        self._client: aiomqtt.Client | None = None
        self._backoff_s = 1.0
        # El motor no es concurrente: eventos, acciones y ticks se procesan de uno en uno.
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._client is not None

    @property
    def engine(self) -> IncidentEngine:
        if self._engine is None:
            raise RuntimeError("service not started")
        return self._engine

    async def run(self) -> None:
        await self._store.open()
        try:
            incidents = await self._store.load_active_incidents()
            self._engine = IncidentEngine(
                self._config,
                timedelta(seconds=self._settings.fusion_window_s),
                incidents,
            )
            logger.info("orchestrator_started", extra={"active_incidents": len(incidents)})
            while True:
                try:
                    await self._serve()
                except* aiomqtt.MqttError as group:
                    logger.warning(
                        "mqtt_disconnected",
                        extra={"error": str(group.exceptions[0]), "retry_in_s": self._backoff_s},
                    )
                self._client = None
                await asyncio.sleep(self._backoff_s)
                self._backoff_s = min(self._backoff_s * 2, MAX_BACKOFF_S)
        finally:
            await self._store.close()

    async def _serve(self) -> None:
        async with aiomqtt.Client(
            hostname=self._settings.mqtt_host,
            port=self._settings.mqtt_port,
            identifier=self._settings.mqtt_client_id,
            clean_session=False,
        ) as client:
            await client.subscribe(EVENTS_SUBSCRIPTION, qos=1)
            await client.subscribe(ACTIONS_TOPIC, qos=1)
            # Solo se considera conectado cuando ya está suscrito.
            self._client = client
            self._backoff_s = 1.0
            logger.info("mqtt_connected", extra={"host": self._settings.mqtt_host})
            async with self._lock:
                await self._publish(self.engine.snapshot_updates(utc_now()))
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._consume(client))
                tg.create_task(self._tick_loop())

    async def _consume(self, client: aiomqtt.Client) -> None:
        async for message in client.messages:
            topic = message.topic.value
            payload = message.payload
            if not isinstance(payload, bytes | bytearray | str):
                logger.warning("unexpected_payload_type", extra={"topic": topic})
                continue
            try:
                if topic == ACTIONS_TOPIC:
                    await self._on_action(payload)
                else:
                    await self._on_event(topic, payload)
            except aiomqtt.MqttError:
                raise
            except Exception:
                logger.exception("message_processing_failed", extra={"topic": topic})

    async def _on_event(self, topic: str, payload: bytes | bytearray | str) -> None:
        try:
            event = Event.model_validate_json(payload)
            check_event_matches_topic(event, topic)
        except ValueError as exc:
            logger.warning("event_rejected", extra={"topic": topic, "error": str(exc)})
            return
        logger.info(
            "event_received",
            extra={
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "zone_id": event.location.zone_id,
                "confidence": event.confidence,
                "severity_hint": event.severity_hint.value,
            },
        )
        async with self._lock:
            if await self._event_already_stored(event.event_id):
                logger.info("duplicate_event_ignored", extra={"event_id": event.event_id})
                return
            try:
                updates = self.engine.handle_event(event, utc_now())
            except EventRejectedError as exc:
                logger.warning(
                    "event_rejected", extra={"event_id": event.event_id, "error": str(exc)}
                )
                return
            await self._persist(updates, event)
            await self._publish(updates)

    async def _on_action(self, payload: bytes | bytearray | str) -> None:
        try:
            action = CaregiverAction.model_validate_json(payload)
        except ValueError as exc:
            logger.warning("action_invalid", extra={"error": str(exc)})
            return
        async with self._lock:
            try:
                updates = self.engine.handle_action(action, utc_now())
            except ActionRejectedError as exc:
                logger.warning(
                    "action_rejected",
                    extra={
                        "action_id": action.action_id,
                        "incident_id": action.incident_id,
                        "staff_id": action.staff_id,
                        "code": exc.code,
                        "error": str(exc),
                    },
                )
                if exc.code == ActionRejectedError.UNKNOWN_INCIDENT:
                    # Autolimpieza: si el backend ve un incidente que el orquestador no conoce
                    # (p. ej. un retenido antiguo), se borra para que desaparezca de la app.
                    await self._clear_retained(action.incident_id)
                return
            await self._persist(updates)
            await self._publish(updates)

    async def _tick_loop(self) -> None:
        while True:
            async with self._lock:
                updates = self.engine.tick(utc_now())
                if updates:
                    await self._persist(updates)
                    await self._publish(updates)
            self._heartbeat()
            await asyncio.sleep(self._settings.tick_interval_s)

    async def _event_already_stored(self, event_id: str) -> bool:
        try:
            return await self._store.event_exists(event_id)
        except Exception:
            # Ante la duda se procesa: mejor un aviso duplicado que perder una caída.
            logger.exception("store_lookup_failed", extra={"event_id": event_id})
            return False

    async def _persist(self, updates: list[IncidentUpdate], event: Event | None = None) -> None:
        try:
            await self._store.save(updates, event)
        except Exception:
            logger.exception(
                "persistence_failed",
                extra={"incident_ids": [u.incident.incident_id for u in updates]},
            )

    async def _publish(self, updates: list[IncidentUpdate]) -> None:
        client = self._require_client()
        for update in updates:
            incident = update.incident
            topic = alert_topic(incident.incident_id)
            await client.publish(topic, update.model_dump_json(), qos=1, retain=True)
            if incident.status is IncidentStatus.RESOLVED:
                await self._clear_retained(incident.incident_id)
            logger.info(
                "incident_update_published",
                extra={
                    "incident_id": incident.incident_id,
                    "reason": update.reason.value,
                    "status": incident.status.value,
                    "priority": incident.priority.value,
                    "stage": int(incident.stage),
                    "new_recipients": update.new_recipients,
                    "version": incident.version,
                },
            )

    async def _clear_retained(self, incident_id: str) -> None:
        # Un mensaje retenido vacío borra el estado guardado en el broker.
        await self._require_client().publish(alert_topic(incident_id), b"", qos=1, retain=True)

    def _require_client(self) -> aiomqtt.Client:
        if self._client is None:
            raise aiomqtt.MqttError("not connected")
        return self._client

    def _heartbeat(self) -> None:
        if self._settings.heartbeat_file is not None:
            self._settings.heartbeat_file.write_text(utc_now().isoformat(), encoding="utf-8")
