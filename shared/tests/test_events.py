"""Tests del esquema común de eventos."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError
from residencia_shared.events import (
    EVENT_TYPE_SOURCE,
    Event,
    EventType,
    Location,
    Severity,
    Source,
)

# Ejemplo del CLAUDE.md con la planta añadida a la ubicación.
EXAMPLE: dict[str, Any] = {
    "event_id": "evt_8f3a2c",
    "timestamp": "2026-10-02T03:14:22Z",
    "source": "fall_detector",
    "event_type": "fall_confirmed",
    "location": {"floor_id": "p1", "zone_id": "hab_12", "zone_type": "room"},
    "confidence": 0.91,
    "severity_hint": "critical",
    "payload": {"immobile_seconds": 18},
}


def _with(**changes: Any) -> dict[str, Any]:
    data = json.loads(json.dumps(EXAMPLE))
    data.update(changes)
    return data


def test_example_event_is_valid_and_round_trips() -> None:
    event = Event.model_validate(EXAMPLE)
    assert event.timestamp == datetime(2026, 10, 2, 3, 14, 22, tzinfo=UTC)
    assert Event.model_validate_json(event.model_dump_json()) == event


def test_timestamp_is_serialized_in_utc_with_z_suffix() -> None:
    event = Event.model_validate(EXAMPLE)
    assert json.loads(event.model_dump_json())["timestamp"] == "2026-10-02T03:14:22Z"


def test_rejects_timestamp_without_timezone() -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(_with(timestamp="2026-10-02T03:14:22"))


def test_rejects_timestamp_not_in_utc() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        Event.model_validate(_with(timestamp="2026-10-02T05:14:22+02:00"))


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_rejects_confidence_out_of_range(confidence: float) -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(_with(confidence=confidence))


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(_with(camera_id="cam_3"))


@pytest.mark.parametrize(
    "field", ["event_id", "timestamp", "source", "event_type", "location", "confidence"]
)
def test_rejects_missing_common_field(field: str) -> None:
    data = _with()
    del data[field]
    with pytest.raises(ValidationError):
        Event.model_validate(data)


def test_payload_defaults_to_empty() -> None:
    data = _with()
    del data["payload"]
    assert Event.model_validate(data).payload == {}


def test_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(_with(event_type="person_dancing"))


def test_rejects_event_type_from_wrong_source() -> None:
    with pytest.raises(ValidationError, match="must come from"):
        Event.model_validate(_with(source="audio_events"))


@pytest.mark.parametrize("zone_id", ["hab 12", "hab/12", "hab_+", "Hab_12", ""])
def test_rejects_ids_that_would_break_mqtt_topics(zone_id: str) -> None:
    with pytest.raises(ValidationError):
        Location(floor_id="p1", zone_id=zone_id, zone_type="room")


def test_events_are_immutable() -> None:
    event = Event.model_validate(EXAMPLE)
    with pytest.raises(ValidationError):
        event.confidence = 0.1  # type: ignore[misc]


def test_create_generates_id_utc_timestamp_and_source() -> None:
    location = Location(floor_id="p1", zone_id="hab_12", zone_type="room")
    before = datetime.now(UTC)
    event = Event.create(
        event_type=EventType.FALL_SUSPECTED,
        location=location,
        confidence=0.8,
        severity_hint=Severity.HIGH,
    )
    assert event.event_id.startswith("evt_")
    assert event.source is Source.FALL_DETECTOR
    assert before <= event.timestamp <= datetime.now(UTC)
    assert event.timestamp.utcoffset() == timedelta(0)


def test_create_rejects_non_utc_timestamp() -> None:
    location = Location(floor_id="p1", zone_id="hab_12", zone_type="room")
    with pytest.raises(ValidationError):
        Event.create(
            event_type=EventType.FALL_SUSPECTED,
            location=location,
            confidence=0.8,
            severity_hint=Severity.HIGH,
            timestamp=datetime(2026, 10, 2, 5, 0, tzinfo=timezone(timedelta(hours=2))),
        )


def test_every_event_type_has_a_source() -> None:
    assert set(EVENT_TYPE_SOURCE) == set(EventType)


def test_severity_ranks_are_ordered() -> None:
    ranks = [s.rank for s in (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)
