"""Tests del motor de reglas."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest
from orchestrator.rules import RULES, describe, rule_for
from residencia_shared.events import Event, EventType, Severity

EventFactory = Callable[..., Event]


def test_every_event_type_has_a_rule() -> None:
    assert set(RULES) == set(EventType)


def test_confirmed_fall_is_always_critical() -> None:
    assert rule_for(EventType.FALL_CONFIRMED).priority is Severity.CRITICAL


def test_suspected_fall_is_high() -> None:
    assert rule_for(EventType.FALL_SUSPECTED).priority is Severity.HIGH


def test_fall_events_share_a_category_so_they_merge() -> None:
    assert (
        rule_for(EventType.FALL_SUSPECTED).category == rule_for(EventType.FALL_CONFIRMED).category
    )


@pytest.mark.parametrize("payload", [{"immobile_seconds": 18}, {"immobile_seconds": 18.4}])
def test_confirmed_message_includes_immobility(
    make_event: EventFactory, night: datetime, payload: dict[str, float]
) -> None:
    event = make_event(EventType.FALL_CONFIRMED, at=night, payload=payload)
    title, message = describe(event, "Habitación 12", "Planta 1")
    assert title == "Caída confirmada"
    assert (
        message == "Caída confirmada en Habitación 12 (Planta 1). Sin movimiento desde hace 18 s."
    )


def test_message_ignores_malformed_payload(make_event: EventFactory, night: datetime) -> None:
    event = make_event(EventType.FALL_CONFIRMED, at=night, payload={"immobile_seconds": "mucho"})
    _, message = describe(event, "Habitación 12", "Planta 1")
    assert message == "Caída confirmada en Habitación 12 (Planta 1)."
