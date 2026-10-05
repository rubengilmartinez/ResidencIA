"""Motor de reglas determinista: prioridad, categoría y texto de cada tipo de evento.

La prioridad la decide siempre esta tabla, no el módulo: ``severity_hint`` y ``confidence``
se registran pero no la modifican. En particular, una caída confirmada es siempre crítica,
responda o no el LLM (que nunca está en este camino).
"""

from __future__ import annotations

from dataclasses import dataclass

from residencia_shared.events import Event, EventType, Severity


@dataclass(frozen=True)
class EventRule:
    # Los eventos de la misma categoría y zona se fusionan en un único incidente.
    category: str
    priority: Severity
    title: str


RULES: dict[EventType, EventRule] = {
    EventType.FALL_SUSPECTED: EventRule("fall", Severity.HIGH, "Posible caída"),
    EventType.FALL_CONFIRMED: EventRule("fall", Severity.CRITICAL, "Caída confirmada"),
}


def rule_for(event_type: EventType) -> EventRule:
    return RULES[event_type]


def describe(event: Event, zone_name: str, floor_name: str) -> tuple[str, str]:
    """Título y mensaje por plantilla. El LLM podrá enriquecerlos más adelante, fuera del
    camino crítico; estos textos son el mínimo garantizado."""
    title = rule_for(event.event_type).title
    message = f"{title} en {zone_name} ({floor_name})."
    immobile = event.payload.get("immobile_seconds")
    if event.event_type is EventType.FALL_CONFIRMED and isinstance(immobile, int | float):
        message += f" Sin movimiento desde hace {immobile:.0f} s."
    return title, message
