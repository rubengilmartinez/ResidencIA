"""Tests del reproductor de escenarios (sin broker: publicador y reloj falsos)."""

from __future__ import annotations

from pathlib import Path

import pytest
from event_player.player import play
from event_player.scenario import Scenario, load_scenario
from pydantic import ValidationError
from residencia_shared.config import SystemConfig
from residencia_shared.events import Event, EventType, Source
from residencia_shared.topics import check_event_matches_topic

SCENARIOS_DIR = Path(__file__).parents[1] / "scenarios"


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def publish(self, topic: str, payload: str) -> None:
        self.messages.append((topic, payload))


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def scenario(*steps: dict[str, object]) -> Scenario:
    return Scenario.model_validate({"name": "t", "description": "t", "steps": list(steps)})


def step(at_s: float, zone_id: str = "hab_12", **extra: object) -> dict[str, object]:
    return {
        "at_s": at_s,
        "event_type": "fall_suspected",
        "zone_id": zone_id,
        "confidence": 0.8,
        "severity_hint": "high",
        **extra,
    }


@pytest.mark.parametrize("path", sorted(SCENARIOS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_bundled_scenarios_are_valid_for_the_real_residence(
    path: Path, system_config: SystemConfig
) -> None:
    load_scenario(path).check_against(system_config.residence)


def test_play_publishes_valid_events_on_matching_topics(system_config: SystemConfig) -> None:
    publisher = FakePublisher()
    events = play(
        load_scenario(SCENARIOS_DIR / "fall_confirmed_hab_12.yaml"),
        system_config.residence,
        publisher,
        sleep=FakeSleep(),
    )
    assert [e.event_type for e in events] == [EventType.FALL_SUSPECTED, EventType.FALL_CONFIRMED]
    for topic, payload in publisher.messages:
        event = Event.model_validate_json(payload)
        check_event_matches_topic(event, topic)
        assert event.source is Source.FALL_DETECTOR
        assert event.location.floor_id == "p1"
    assert publisher.messages[0][0] == "residencia/p1/hab_12/caidas"


def test_play_respects_relative_times_and_speed(system_config: SystemConfig) -> None:
    sleep = FakeSleep()
    play(
        scenario(step(0), step(4), step(10)),
        system_config.residence,
        FakePublisher(),
        speed=2.0,
        sleep=sleep,
    )
    assert sleep.calls == [2.0, 3.0]


def test_fixed_event_id_reproduces_duplicates(system_config: SystemConfig) -> None:
    publisher = FakePublisher()
    events = play(
        load_scenario(SCENARIOS_DIR / "duplicate_delivery_hab_05.yaml"),
        system_config.residence,
        publisher,
        sleep=FakeSleep(),
    )
    assert len({e.event_id for e in events}) == 1
    assert len(publisher.messages) == 2


def test_rejects_steps_out_of_order() -> None:
    with pytest.raises(ValidationError, match="ordered"):
        scenario(step(5), step(1))


def test_rejects_unknown_zone_before_publishing(system_config: SystemConfig) -> None:
    publisher = FakePublisher()
    with pytest.raises(ValueError, match="unknown zones"):
        play(
            scenario(step(0), step(1, zone_id="hab_99")),
            system_config.residence,
            publisher,
            sleep=FakeSleep(),
        )
    assert publisher.messages == []


def test_rejects_non_positive_speed(system_config: SystemConfig) -> None:
    with pytest.raises(ValueError, match="speed"):
        play(scenario(step(0)), system_config.residence, FakePublisher(), speed=0)
