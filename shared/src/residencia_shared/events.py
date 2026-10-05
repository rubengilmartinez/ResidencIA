"""Esquema común de eventos que publican todos los módulos de IA.

Es el contrato entre los módulos y el resto del sistema. Se define una sola vez aquí y lo
reutilizan todos los servicios. Los campos comunes son obligatorios; ``payload`` es
específico de cada módulo.

El esquema es deliberadamente estricto (campos extra prohibidos, enumerados cerrados,
UTC obligatorio): un evento mal formado se rechaza en la frontera en lugar de propagar
datos ambiguos al orquestador.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# Identificadores de planta y zona: forman parte de los temas MQTT, así que no pueden
# contener "/", "+" ni "#".
ID_PATTERN = r"^[a-z0-9_]+$"


def ensure_utc(value: datetime) -> datetime:
    """Exige que un datetime con zona horaria esté en UTC y normaliza su tzinfo."""
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be in UTC")
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(ensure_utc)]


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


class Source(StrEnum):
    FALL_DETECTOR = "fall_detector"
    POSTURE_MONITOR = "posture_monitor"
    AUDIO_EVENTS = "audio_events"
    VOICE_ASSISTANT = "voice_assistant"


class EventType(StrEnum):
    # Detector de caídas: primero la sospecha y, tras comprobar la inmovilidad, la confirmación.
    FALL_SUSPECTED = "fall_suspected"
    FALL_CONFIRMED = "fall_confirmed"


# Qué módulo puede emitir cada tipo de evento. Se amplía al diseñar cada módulo nuevo.
EVENT_TYPE_SOURCE: dict[EventType, Source] = {
    EventType.FALL_SUSPECTED: Source.FALL_DETECTOR,
    EventType.FALL_CONFIRMED: Source.FALL_DETECTOR,
}


class ZoneType(StrEnum):
    ROOM = "room"
    CORRIDOR = "corridor"
    DINING_ROOM = "dining_room"
    LIVING_ROOM = "living_room"
    BATHROOM = "bathroom"
    GARDEN = "garden"


class Location(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    floor_id: str = Field(pattern=ID_PATTERN)
    zone_id: str = Field(pattern=ID_PATTERN)
    zone_type: ZoneType


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(pattern=r"^evt_[a-z0-9]{6,}$")
    timestamp: UtcDatetime
    source: Source
    event_type: EventType
    location: Location
    confidence: float = Field(ge=0.0, le=1.0)
    severity_hint: Severity
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _event_type_matches_source(self) -> Self:
        expected = EVENT_TYPE_SOURCE[self.event_type]
        if self.source != expected:
            raise ValueError(
                f"event_type '{self.event_type}' must come from '{expected}', not '{self.source}'"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        event_type: EventType,
        location: Location,
        confidence: float,
        severity_hint: Severity,
        payload: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
        event_id: str | None = None,
    ) -> Self:
        """Construye un evento nuevo con id y marca de tiempo generados.

        El ``source`` se deduce del tipo de evento para que no puedan contradecirse.
        """
        return cls(
            event_id=event_id or new_id("evt"),
            timestamp=timestamp or utc_now(),
            source=EVENT_TYPE_SOURCE[event_type],
            event_type=event_type,
            location=location,
            confidence=confidence,
            severity_hint=severity_hint,
            payload=payload or {},
        )
