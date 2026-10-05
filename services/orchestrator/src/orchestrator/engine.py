"""Núcleo del orquestador: fusión de eventos en incidentes y escalado.

Es código puro, sin E/S ni reloj propio: cada operación recibe ``now`` explícitamente y
devuelve los cambios (``IncidentUpdate``) que el servicio debe persistir y publicar. Así el
escalado se prueba con un reloj simulado, sin esperas reales y con resultados siempre
reproducibles.

Política de escalado (ver docs/decisions/0004-escalation-policy.md):

- Etapa 1: cuidadores de la zona. Etapa 2: cuidadores de la planta. Etapa 3: todo el
  personal de turno, supervisor incluido. Los avisos son acumulativos.
- El plazo de cada etapa cuenta desde que se envió y depende de la prioridad actual del
  incidente (``config/escalation.yaml``). Si la prioridad sube, el plazo se recalcula
  desde el mismo inicio de etapa, así que puede vencer en ese mismo instante.
- Una etapa que no añade a nadie nuevo se salta.
- Aceptar detiene el escalado. Solo cuenta la primera aceptación.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

from residencia_shared.config import SystemConfig
from residencia_shared.events import Event, ensure_utc, new_id
from residencia_shared.internal import (
    CaregiverAction,
    CaregiverActionType,
    EscalationStage,
    Incident,
    IncidentStatus,
    IncidentUpdate,
    UpdateReason,
)

from orchestrator.rules import describe, rule_for

logger = logging.getLogger(__name__)

# Cuánto tiempo se recuerdan los event_id ya procesados (MQTT con QoS 1 puede duplicar).
DEDUP_TTL = timedelta(hours=1)


class EventRejectedError(Exception):
    """El evento es válido según el esquema pero no encaja con la configuración."""


class ActionRejectedError(Exception):
    """La acción del cuidador no se puede aplicar (incidente desconocido, ya aceptado...)."""

    UNKNOWN_INCIDENT = "unknown_incident"
    UNKNOWN_STAFF = "unknown_staff"
    NOT_OPEN = "not_open"

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class IncidentEngine:
    def __init__(
        self,
        config: SystemConfig,
        fusion_window: timedelta,
        incidents: Iterable[Incident] = (),
    ) -> None:
        self._config = config
        self._fusion_window = fusion_window
        self._incidents: dict[str, Incident] = {}
        self._seen_events: dict[str, datetime] = {}
        # Restaura incidentes persistidos: el escalado continúa desde stage_started_at.
        for incident in incidents:
            if incident.status is IncidentStatus.RESOLVED:
                continue
            self._incidents[incident.incident_id] = incident
            for event_id in incident.event_ids:
                self._seen_events[event_id] = incident.last_event_at

    @property
    def active_incidents(self) -> list[Incident]:
        """Incidentes no resueltos (abiertos o aceptados)."""
        return list(self._incidents.values())

    # --- Eventos ------------------------------------------------------------------------

    def handle_event(self, event: Event, now: datetime) -> list[IncidentUpdate]:
        now = ensure_utc(now)
        if event.event_id in self._seen_events:
            logger.info("duplicate_event_ignored", extra={"event_id": event.event_id})
            return []
        self._check_location(event)
        self._seen_events[event.event_id] = now

        rule = rule_for(event.event_type)
        incident = self._find_fusable(event, rule.category, now)
        if incident is None:
            return [self._create(event, now)]
        return self._merge(incident, event, now)

    def _check_location(self, event: Event) -> None:
        residence = self._config.residence
        zone_id = event.location.zone_id
        if not residence.has_zone(zone_id):
            raise EventRejectedError(f"unknown zone {zone_id!r}")
        expected = residence.location(zone_id)
        if event.location != expected:
            raise EventRejectedError(
                f"location mismatch for zone {zone_id!r}: got {event.location}, expected {expected}"
            )

    def _find_fusable(self, event: Event, category: str, now: datetime) -> Incident | None:
        candidates = [
            inc
            for inc in self._incidents.values()
            if inc.location.zone_id == event.location.zone_id
            and inc.category == category
            and now - inc.last_event_at <= self._fusion_window
        ]
        return max(candidates, key=lambda inc: inc.last_event_at, default=None)

    def _create(self, event: Event, now: datetime) -> IncidentUpdate:
        rule = rule_for(event.event_type)
        title, message = self._describe(event)
        incident = Incident(
            incident_id=new_id("inc"),
            version=1,
            category=rule.category,
            status=IncidentStatus.OPEN,
            priority=rule.priority,
            location=event.location,
            title=title,
            message=message,
            stage=EscalationStage.ZONE_CAREGIVER,
            stage_started_at=now,
            notified=[],
            created_at=now,
            updated_at=now,
            last_event_at=now,
            last_event_type=event.event_type,
            event_ids=[event.event_id],
        )
        new_recipients = self._enter_stage(incident, EscalationStage.ZONE_CAREGIVER, now)
        self._incidents[incident.incident_id] = incident
        return self._update(incident, UpdateReason.CREATED, new_recipients, now)

    def _merge(self, incident: Incident, event: Event, now: datetime) -> list[IncidentUpdate]:
        rule = rule_for(event.event_type)
        incident.event_ids.append(event.event_id)
        incident.last_event_at = now
        incident.last_event_type = event.event_type
        reason = UpdateReason.EVENT_ADDED
        if rule.priority.rank > incident.priority.rank:
            incident.priority = rule.priority
            incident.title, incident.message = self._describe(event)
            reason = UpdateReason.PRIORITY_RAISED
        self._touch(incident, now)
        updates = [self._update(incident, reason, [], now)]
        # Con más prioridad el plazo de la etapa actual es más corto y puede haber vencido ya.
        updates.extend(self._escalate_if_due(incident, now))
        return updates

    def _describe(self, event: Event) -> tuple[str, str]:
        residence = self._config.residence
        zone = residence.zone(event.location.zone_id)
        floor = residence.floor_of(event.location.zone_id)
        return describe(event, zone.name, floor.name)

    # --- Escalado -----------------------------------------------------------------------

    def tick(self, now: datetime) -> list[IncidentUpdate]:
        """Avanza el escalado de todos los incidentes cuyo plazo haya vencido."""
        now = ensure_utc(now)
        updates: list[IncidentUpdate] = []
        for incident in list(self._incidents.values()):
            updates.extend(self._escalate_if_due(incident, now))
        self._seen_events = {
            event_id: seen_at
            for event_id, seen_at in self._seen_events.items()
            if now - seen_at <= DEDUP_TTL
        }
        return updates

    def deadline(self, incident: Incident) -> datetime | None:
        """Momento en que vence la etapa actual (None si no aplica)."""
        if incident.status is not IncidentStatus.OPEN:
            return None
        timeout = self._config.escalation.timeout(incident.stage, incident.priority)
        return None if timeout is None else incident.stage_started_at + timeout

    def _escalate_if_due(self, incident: Incident, now: datetime) -> list[IncidentUpdate]:
        deadline = self.deadline(incident)
        if deadline is None or now < deadline:
            return []
        new_recipients = self._enter_stage(incident, EscalationStage(incident.stage + 1), now)
        self._touch(incident, now)
        return [self._update(incident, UpdateReason.ESCALATED, new_recipients, now)]

    def _enter_stage(self, incident: Incident, stage: EscalationStage, now: datetime) -> list[str]:
        """Pasa el incidente a ``stage``; si no añade a nadie, sigue a la siguiente etapa.

        Devuelve las personas avisadas por primera vez.
        """
        targets = self._config.stage_targets(stage, incident.location, now)
        new = [staff_id for staff_id in targets if staff_id not in incident.notified]
        if not new and stage < EscalationStage.ALL_STAFF:
            return self._enter_stage(incident, EscalationStage(stage + 1), now)
        incident.stage = stage
        incident.stage_started_at = now
        incident.notified = [*incident.notified, *new]
        return new

    # --- Acciones de cuidadores ---------------------------------------------------------

    def handle_action(self, action: CaregiverAction, now: datetime) -> list[IncidentUpdate]:
        now = ensure_utc(now)
        incident = self._incidents.get(action.incident_id)
        if incident is None:
            raise ActionRejectedError(
                ActionRejectedError.UNKNOWN_INCIDENT,
                f"unknown or already resolved incident {action.incident_id!r}",
            )
        if self._config.staff_member(action.staff_id) is None:
            raise ActionRejectedError(
                ActionRejectedError.UNKNOWN_STAFF, f"unknown staff member {action.staff_id!r}"
            )

        if action.action is CaregiverActionType.ACCEPT:
            if incident.status is not IncidentStatus.OPEN:
                raise ActionRejectedError(
                    ActionRejectedError.NOT_OPEN,
                    f"incident {incident.incident_id!r} already accepted by "
                    f"{incident.accepted_by!r}",
                )
            incident.status = IncidentStatus.ACCEPTED
            incident.accepted_by = action.staff_id
            incident.accepted_at = now
            reason = UpdateReason.ACCEPTED
        else:
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_by = action.staff_id
            incident.resolved_at = now
            del self._incidents[incident.incident_id]
            reason = UpdateReason.RESOLVED

        self._touch(incident, now)
        return [self._update(incident, reason, [], now)]

    # --- Utilidades ---------------------------------------------------------------------

    def snapshot_updates(self, now: datetime) -> list[IncidentUpdate]:
        """Estado actual de todos los incidentes activos, para republicarlo tras un reinicio.

        No incrementa la versión: el backend descarta lo que ya tenía.
        """
        now = ensure_utc(now)
        return [
            self._update(incident, UpdateReason.RESTORED, [], now)
            for incident in self._incidents.values()
        ]

    @staticmethod
    def _touch(incident: Incident, now: datetime) -> None:
        incident.version += 1
        incident.updated_at = now

    @staticmethod
    def _update(
        incident: Incident, reason: UpdateReason, new_recipients: list[str], now: datetime
    ) -> IncidentUpdate:
        return IncidentUpdate(
            message_id=new_id("msg"),
            timestamp=now,
            reason=reason,
            new_recipients=new_recipients,
            incident=incident.model_copy(deep=True),
        )
