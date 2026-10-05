"""Mensajes internos entre orquestador y backend (temas ``sistema/...``).

- El orquestador publica el estado de cada incidente en ``sistema/alertas/{incident_id}``
  (mensaje retenido, así el backend recupera el estado completo al reconectarse).
- El backend publica las acciones de los cuidadores en ``sistema/acciones``.

El orquestador es el único que modifica el estado de un incidente; el backend solo lo
refleja. Así, si dos cuidadores aceptan a la vez, gana el primero que procesa el
orquestador, sin carreras entre escritores.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field

from residencia_shared.events import EventType, Location, Severity, UtcDatetime

INCIDENT_ID_PATTERN = r"^inc_[a-z0-9]+$"


class IncidentStatus(StrEnum):
    OPEN = "open"  # avisando a cuidadores, nadie lo ha aceptado aún
    # El módulo lo ha marcado como falsa alarma: no escala, pero un cuidador debe revisarlo.
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"  # un cuidador ha dicho "yo me encargo"
    RESOLVED = "resolved"


class EscalationStage(IntEnum):
    ZONE_CAREGIVER = 1  # cuidadores responsables de la zona
    FLOOR = 2  # todos los cuidadores de la planta
    ALL_STAFF = 3  # todo el personal de turno, supervisor incluido


class UpdateReason(StrEnum):
    CREATED = "created"
    EVENT_ADDED = "event_added"
    PRIORITY_RAISED = "priority_raised"
    DISMISSED = "dismissed"  # falsa alarma: baja prioridad, sin escalado, pendiente de revisión
    ESCALATED = "escalated"
    ACCEPTED = "accepted"
    RESOLVED = "resolved"
    RESTORED = "restored"  # reenvío del estado tras reiniciar el orquestador


class Incident(BaseModel):
    """Estado completo de un incidente. Lo que ve el backend es siempre una copia de esto."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    incident_id: str = Field(pattern=INCIDENT_ID_PATTERN)
    # Se incrementa en cada cambio; permite descartar mensajes duplicados o desordenados.
    version: int = Field(ge=1)
    category: str
    status: IncidentStatus
    priority: Severity
    location: Location
    title: str
    message: str
    stage: EscalationStage
    stage_started_at: UtcDatetime
    # Personas avisadas hasta ahora (acumulado, en orden de aviso).
    notified: list[str]
    accepted_by: str | None = None
    accepted_at: UtcDatetime | None = None
    resolved_by: str | None = None
    resolved_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    last_event_at: UtcDatetime
    last_event_type: EventType
    event_ids: list[str]


class IncidentUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str
    timestamp: UtcDatetime
    reason: UpdateReason
    # Personas que reciben aviso por primera vez con este cambio.
    new_recipients: list[str]
    incident: Incident


class CaregiverActionType(StrEnum):
    ACCEPT = "accept"
    RESOLVE = "resolve"


class CaregiverAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    timestamp: UtcDatetime
    incident_id: str = Field(pattern=INCIDENT_ID_PATTERN)
    staff_id: str = Field(pattern=r"^[a-z0-9_]+$")
    action: CaregiverActionType
