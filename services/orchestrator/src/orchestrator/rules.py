"""Motor de reglas determinista: prioridad, categoría y texto de cada tipo de evento.

La prioridad la decide siempre esta tabla, no el módulo: ``severity_hint`` y ``confidence``
se registran pero no la modifican. En particular, una caída confirmada es siempre crítica,
responda o no el LLM (que nunca está en este camino).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from residencia_shared.events import Event, EventType, Severity


class RuleKind(StrEnum):
    # Abre un incidente o se fusiona con uno abierto de la misma categoría y zona.
    ALERT = "alert"
    # El módulo retira su sospecha (falsa alarma). Nunca abre incidentes ni rebaja uno
    # crítico; ver docs/decisions/0006-fall-false-alarm.md.
    DISMISSAL = "dismissal"


@dataclass(frozen=True)
class EventRule:
    # Los eventos de la misma categoría y zona se fusionan en un único incidente.
    category: str
    # En una retirada (DISMISSAL), prioridad a la que baja el incidente no crítico.
    priority: Severity
    title: str
    kind: RuleKind = RuleKind.ALERT


RULES: dict[EventType, EventRule] = {
    EventType.FALL_SUSPECTED: EventRule("fall", Severity.HIGH, "Posible caída"),
    EventType.FALL_CONFIRMED: EventRule("fall", Severity.CRITICAL, "Caída confirmada"),
    EventType.FALL_DISMISSED: EventRule(
        "fall", Severity.LOW, "Revisar posible caída", kind=RuleKind.DISMISSAL
    ),
}

# Nota que se añade a un incidente crítico cuando el detector informa de que la persona se ha
# levantado: el incidente sigue siendo crítico.
RECOVERY_NOTE = "El detector indica que la persona se ha levantado."


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
    if event.event_type is EventType.FALL_DISMISSED:
        message += f" {RECOVERY_NOTE} Compruébalo cuando puedas."
    return title, message
