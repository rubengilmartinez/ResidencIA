"""Temas MQTT del sistema.

Dos espacios de nombres separados:

- ``residencia/{planta}/{zona}/{modulo}``: eventos que publican los módulos de IA.
- ``sistema/...``: bus interno entre orquestador y backend (alertas y acciones de
  cuidadores). Ningún módulo de IA publica ni se suscribe aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from residencia_shared.events import Event, Source

ROOT = "residencia"
EVENTS_SUBSCRIPTION = f"{ROOT}/+/+/+"

SYSTEM_ROOT = "sistema"
ALERTS_PREFIX = f"{SYSTEM_ROOT}/alertas"
ALERTS_SUBSCRIPTION = f"{ALERTS_PREFIX}/+"
ACTIONS_TOPIC = f"{SYSTEM_ROOT}/acciones"

_SEGMENT = re.compile(r"^[a-z0-9_]+$")


class Module(StrEnum):
    CAIDAS = "caidas"
    POSTURA = "postura"
    AUDIO = "audio"
    VOZ = "voz"


SOURCE_MODULE: dict[Source, Module] = {
    Source.FALL_DETECTOR: Module.CAIDAS,
    Source.POSTURE_MONITOR: Module.POSTURA,
    Source.AUDIO_EVENTS: Module.AUDIO,
    Source.VOICE_ASSISTANT: Module.VOZ,
}


@dataclass(frozen=True)
class EventTopic:
    floor_id: str
    zone_id: str
    module: Module

    def __str__(self) -> str:
        return f"{ROOT}/{self.floor_id}/{self.zone_id}/{self.module}"


def _check_segment(value: str, name: str) -> None:
    if not _SEGMENT.fullmatch(value):
        raise ValueError(f"invalid {name} segment: {value!r}")


def event_topic(event: Event) -> str:
    """Tema en el que un módulo debe publicar el evento."""
    loc = event.location
    return str(EventTopic(loc.floor_id, loc.zone_id, SOURCE_MODULE[event.source]))


def parse_event_topic(topic: str) -> EventTopic:
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != ROOT:
        raise ValueError(f"not an event topic: {topic!r}")
    _, floor_id, zone_id, module = parts
    _check_segment(floor_id, "floor")
    _check_segment(zone_id, "zone")
    try:
        parsed_module = Module(module)
    except ValueError:
        raise ValueError(f"unknown module in topic: {module!r}") from None
    return EventTopic(floor_id, zone_id, parsed_module)


def check_event_matches_topic(event: Event, topic: str) -> None:
    """Rechaza eventos cuyo contenido contradice el tema por el que llegaron."""
    parsed = parse_event_topic(topic)
    expected = EventTopic(
        event.location.floor_id, event.location.zone_id, SOURCE_MODULE[event.source]
    )
    if parsed != expected:
        raise ValueError(f"event does not match topic: topic={topic!r} expected={expected}")


def alert_topic(incident_id: str) -> str:
    _check_segment(incident_id, "incident")
    return f"{ALERTS_PREFIX}/{incident_id}"


def parse_alert_topic(topic: str) -> str:
    prefix = f"{ALERTS_PREFIX}/"
    if not topic.startswith(prefix):
        raise ValueError(f"not an alert topic: {topic!r}")
    incident_id = topic.removeprefix(prefix)
    _check_segment(incident_id, "incident")
    return incident_id


def topic_matches(subscription: str, topic: str) -> bool:
    """Comprueba si un tema encaja en un filtro MQTT con comodines ``+`` y ``#``."""
    sub_parts = subscription.split("/")
    topic_parts = topic.split("/")
    for i, sub in enumerate(sub_parts):
        if sub == "#":
            return True
        if i >= len(topic_parts):
            return False
        if sub not in ("+", topic_parts[i]):
            return False
    return len(sub_parts) == len(topic_parts)
