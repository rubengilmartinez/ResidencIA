"""Reproducción de escenarios: publica cada evento en su tema y en su momento."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

import paho.mqtt.client as mqtt
from residencia_shared.config import ResidenceConfig
from residencia_shared.events import Event, utc_now
from residencia_shared.topics import event_topic

from event_player.scenario import Scenario, build_event

logger = logging.getLogger(__name__)


class Publisher(Protocol):
    def publish(self, topic: str, payload: str) -> None: ...


class MqttPublisher:
    """Publicador MQTT síncrono con QoS 1 (espera la confirmación del broker)."""

    CONNECT_TIMEOUT_S = 10.0

    def __init__(self, host: str, port: int, client_id: str = "") -> None:
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._client.on_connect = self._on_connect
        self._connected = threading.Event()
        self._host = host
        self._port = port

    def _on_connect(self, *_: object) -> None:
        self._connected.set()

    def __enter__(self) -> MqttPublisher:
        self._client.connect(self._host, self._port)
        self._client.loop_start()
        # Sin esperar al CONNACK, el primer mensaje queda en cola hasta el siguiente ciclo
        # del bucle de red de paho (hasta 1 s de retraso).
        if not self._connected.wait(self.CONNECT_TIMEOUT_S):
            self._client.loop_stop()
            raise ConnectionError(f"no CONNACK from MQTT broker at {self._host}:{self._port}")
        return self

    def __exit__(self, *_: object) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, topic: str, payload: str) -> None:
        info = self._client.publish(topic, payload, qos=1)
        info.wait_for_publish(timeout=10)
        if not info.is_published():
            raise RuntimeError(f"publish to {topic} not confirmed by the broker")


def play(
    scenario: Scenario,
    residence: ResidenceConfig,
    publisher: Publisher,
    *,
    speed: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Event]:
    """Publica los pasos respetando sus tiempos relativos (divididos por ``speed``)."""
    if speed <= 0:
        raise ValueError("speed must be positive")
    scenario.check_against(residence)
    published: list[Event] = []
    elapsed = 0.0
    for step in scenario.steps:
        wait = (step.at_s - elapsed) / speed
        if wait > 0:
            sleep(wait)
        elapsed = step.at_s
        event = build_event(step, residence, utc_now())
        topic = event_topic(event)
        publisher.publish(topic, event.model_dump_json())
        logger.info(
            "event_published",
            extra={
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "topic": topic,
            },
        )
        published.append(event)
    return published
