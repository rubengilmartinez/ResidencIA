"""Tests de los temas MQTT."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest
from residencia_shared.events import Event, EventType, Source
from residencia_shared.topics import (
    ACTIONS_TOPIC,
    ALERTS_SUBSCRIPTION,
    EVENTS_SUBSCRIPTION,
    SOURCE_MODULE,
    EventTopic,
    Module,
    alert_topic,
    check_event_matches_topic,
    event_topic,
    parse_alert_topic,
    parse_event_topic,
    topic_matches,
)

EventFactory = Callable[..., Event]


def test_event_topic_follows_convention(make_event: EventFactory, night: datetime) -> None:
    event = make_event(EventType.FALL_CONFIRMED, "hab_12", at=night)
    assert event_topic(event) == "residencia/p1/hab_12/caidas"


def test_event_topic_for_common_zone(make_event: EventFactory, night: datetime) -> None:
    event = make_event(EventType.FALL_SUSPECTED, "comedor", at=night)
    assert event_topic(event) == "residencia/p0/comedor/caidas"


def test_parse_event_topic() -> None:
    assert parse_event_topic("residencia/p0/comedor/voz") == EventTopic("p0", "comedor", Module.VOZ)


@pytest.mark.parametrize(
    "topic",
    [
        "residencia/p1/hab_12",  # faltan segmentos
        "residencia/p1/hab_12/caidas/extra",  # sobran segmentos
        "otra/p1/hab_12/caidas",  # raíz incorrecta
        "residencia/p1/hab_12/bailes",  # módulo desconocido
        "residencia/p1/+/caidas",  # comodines no son temas válidos
        "residencia/P1/hab_12/caidas",  # mayúsculas
        "residencia//hab_12/caidas",  # segmento vacío
    ],
)
def test_parse_event_topic_rejects_malformed(topic: str) -> None:
    with pytest.raises(ValueError, match=r"topic|segment|module"):
        parse_event_topic(topic)


def test_check_event_matches_topic_accepts_consistent_event(
    make_event: EventFactory, night: datetime
) -> None:
    event = make_event(at=night)
    check_event_matches_topic(event, event_topic(event))


@pytest.mark.parametrize(
    "topic",
    [
        "residencia/p0/hab_12/caidas",  # planta equivocada
        "residencia/p1/hab_13/caidas",  # zona equivocada
        "residencia/p1/hab_12/audio",  # módulo equivocado
    ],
)
def test_check_event_matches_topic_rejects_mismatch(
    make_event: EventFactory, night: datetime, topic: str
) -> None:
    with pytest.raises(ValueError, match="does not match"):
        check_event_matches_topic(make_event(at=night), topic)


def test_every_source_has_a_module() -> None:
    assert set(SOURCE_MODULE) == set(Source)
    assert len(set(SOURCE_MODULE.values())) == len(Source)


def test_alert_topic_round_trip() -> None:
    topic = alert_topic("inc_abc123")
    assert topic == "sistema/alertas/inc_abc123"
    assert parse_alert_topic(topic) == "inc_abc123"


@pytest.mark.parametrize("incident_id", ["inc/1", "#", "+", ""])
def test_alert_topic_rejects_ids_that_would_inject_wildcards(incident_id: str) -> None:
    with pytest.raises(ValueError, match="segment"):
        alert_topic(incident_id)


def test_internal_topics_are_outside_the_event_namespace() -> None:
    for topic in (ACTIONS_TOPIC, alert_topic("inc_1")):
        assert not topic_matches(EVENTS_SUBSCRIPTION, topic)
        assert not topic_matches("residencia/#", topic)
    assert not topic_matches(ALERTS_SUBSCRIPTION, "residencia/p1/hab_12/caidas")


@pytest.mark.parametrize(
    ("subscription", "topic", "expected"),
    [
        ("residencia/+/+/+", "residencia/p1/hab_12/caidas", True),
        ("residencia/+/+/+", "residencia/p1/hab_12", False),
        ("residencia/#", "residencia/p1/hab_12/caidas", True),
        ("sistema/alertas/+", "sistema/alertas/inc_1", True),
        ("sistema/alertas/+", "sistema/alertas/inc_1/x", False),
        ("a/b", "a/b", True),
        ("a/b", "a/c", False),
    ],
)
def test_topic_matches(subscription: str, topic: str, expected: bool) -> None:
    assert topic_matches(subscription, topic) is expected
