"""Escenarios de eventos pregrabados.

Un escenario es una secuencia de pasos con su instante relativo (``at_s``). La ubicación
completa (planta y tipo de zona) y el módulo de origen se deducen de la configuración y
del tipo de evento, así que un escenario no puede contradecir a la residencia.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, model_validator
from residencia_shared.config import ResidenceConfig, load_yaml
from residencia_shared.events import ID_PATTERN, Event, EventType, Severity


class ScenarioStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    at_s: NonNegativeFloat
    event_type: EventType
    zone_id: str = Field(pattern=ID_PATTERN)
    confidence: float = Field(ge=0.0, le=1.0)
    severity_hint: Severity
    payload: dict[str, Any] = Field(default_factory=dict)
    # Opcional: fija el id para reproducir duplicados (QoS 1 puede entregar dos veces).
    event_id: str | None = None


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    steps: list[ScenarioStep] = Field(min_length=1)

    @model_validator(mode="after")
    def _steps_in_order(self) -> Self:
        times = [step.at_s for step in self.steps]
        if times != sorted(times):
            raise ValueError("steps must be ordered by at_s")
        return self

    def check_against(self, residence: ResidenceConfig) -> None:
        unknown = sorted({s.zone_id for s in self.steps if not residence.has_zone(s.zone_id)})
        if unknown:
            raise ValueError(f"scenario '{self.name}' uses unknown zones: {unknown}")


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate(load_yaml(path))


def build_event(step: ScenarioStep, residence: ResidenceConfig, timestamp: datetime) -> Event:
    return Event.create(
        event_type=step.event_type,
        location=residence.location(step.zone_id),
        confidence=step.confidence,
        severity_hint=step.severity_hint,
        payload=step.payload,
        timestamp=timestamp,
        event_id=step.event_id,
    )
