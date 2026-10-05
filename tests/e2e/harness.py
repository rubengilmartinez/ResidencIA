"""Arnés de los tests de extremo a extremo.

Dos formas de levantar el sistema bajo prueba (variable ``E2E_TARGET``):

- ``compose`` (por defecto): el sistema real con Docker Compose, Mosquitto y PostgreSQL.
  Hay que levantarlo antes (ver tests/e2e/README.md).
- ``inprocess``: broker MQTT en Python (amqtt), orquestador con almacén en memoria y
  backend con uvicorn, todo en un hilo de este proceso. No necesita Docker; sirve para
  comprobar el cableado MQTT en Windows. No prueba Postgres ni los Dockerfiles.

Los tests no dependen de la hora: calculan los destinatarios esperados con la misma
configuración que el orquestador, sea turno de día o de noche.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx2 as httpx
from event_player.player import MqttPublisher
from residencia_shared.config import SystemConfig, load_system_config
from residencia_shared.events import Event, EventType, Severity, utc_now
from residencia_shared.topics import event_topic
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

REPO_ROOT = Path(__file__).parents[2]
CONFIG_DIR = REPO_ROOT / "config"
TEST_ESCALATION = Path(__file__).parent / "config" / "escalation.yaml"
COMPOSE_FILES = ["-f", "docker-compose.yml", "-f", "docker-compose.test.yml"]
COMPOSE_PROJECT = os.environ.get("E2E_COMPOSE_PROJECT", "residencia-test")

Message = dict[str, Any]


class SystemUnderTest(Protocol):
    mqtt_host: str
    mqtt_port: int
    backend_url: str
    config: SystemConfig

    def restart_orchestrator(self) -> None: ...


# --- Clientes ----------------------------------------------------------------------------


class Caregiver:
    """Cliente WebSocket de un cuidador.

    Un hilo lee continuamente y anota la hora de LLEGADA de cada mensaje, para que las
    medidas de tiempo no dependan de cuándo los consulta el test.
    """

    def __init__(self, sut: SystemUnderTest, staff_id: str) -> None:
        self.staff_id = staff_id
        ws_url = sut.backend_url.replace("http://", "ws://")
        self._ws: ClientConnection = connect(f"{ws_url}/ws/{staff_id}", open_timeout=10)
        self.received: list[tuple[float, Message]] = []
        self._queue: queue.Queue[Message] = queue.Queue()
        self._reader = threading.Thread(target=self._read_forever, daemon=True)
        self._reader.start()
        snapshot = self._recv(timeout=5)
        assert snapshot["type"] == "snapshot", snapshot

    def _read_forever(self) -> None:
        with contextlib.suppress(ConnectionClosed):
            for raw in self._ws:
                message: Message = json.loads(raw)
                self.received.append((time.monotonic(), message))
                self._queue.put(message)

    def _recv(self, timeout: float) -> Message:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError from None

    def wait_for(
        self, predicate: Callable[[Message], bool], timeout: float = 10.0, what: str = ""
    ) -> Message:
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                message = self._recv(timeout=remaining)
            except TimeoutError:
                break
            if predicate(message):
                return message
        raise AssertionError(f"{self.staff_id}: no message matching {what or predicate}")

    def updates_for(self, incident_id: str) -> list[tuple[float, Message]]:
        return [
            (t, m)
            for t, m in self.received
            if m["type"] == "incident_update"
            and m["data"]["incident"]["incident_id"] == incident_id
        ]

    def drain(self, seconds: float) -> list[Message]:
        """Recoge lo que llegue durante ``seconds`` (para comprobar que NO llega nada)."""
        got: list[Message] = []
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                got.append(self._recv(timeout=remaining))
            except TimeoutError:
                break
        return got

    def close(self) -> None:
        self._ws.close()


def update_matches(
    zone_id: str | None = None,
    *,
    incident_id: str | None = None,
    reason: str | None = None,
    stage: int | None = None,
    status: str | None = None,
) -> Callable[[Message], bool]:
    def predicate(message: Message) -> bool:
        if message["type"] != "incident_update":
            return False
        data = message["data"]
        inc = data["incident"]
        return (
            (zone_id is None or inc["location"]["zone_id"] == zone_id)
            and (incident_id is None or inc["incident_id"] == incident_id)
            and (reason is None or data["reason"] == reason)
            and (stage is None or inc["stage"] == stage)
            and (status is None or inc["status"] == status)
        )

    return predicate


@dataclass
class Residence:
    """Acciones sobre el sistema bajo prueba: publicar eventos y actuar como cuidador."""

    sut: SystemUnderTest
    http: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        self.http = httpx.Client(base_url=self.sut.backend_url, timeout=10)

    def publish(self, event_type: EventType, zone_id: str, **payload: Any) -> Event:
        event = Event.create(
            event_type=event_type,
            location=self.sut.config.residence.location(zone_id),
            confidence=0.9,
            severity_hint=Severity.CRITICAL
            if event_type is EventType.FALL_CONFIRMED
            else Severity.HIGH,
            payload=payload,
        )
        self.publish_raw(event_topic(event), event.model_dump_json())
        return event

    def publish_raw(self, topic: str, payload: str) -> None:
        with MqttPublisher(self.sut.mqtt_host, self.sut.mqtt_port) as publisher:
            publisher.publish(topic, payload)

    def accept(self, incident_id: str, staff_id: str) -> httpx.Response:
        return self.http.post(f"/incidents/{incident_id}/accept", json={"staff_id": staff_id})

    def resolve(self, incident_id: str, staff_id: str) -> httpx.Response:
        return self.http.post(f"/incidents/{incident_id}/resolve", json={"staff_id": staff_id})

    def active_incidents(self, zone_id: str | None = None) -> list[Message]:
        incidents: list[Message] = self.http.get("/incidents").json()
        return [i for i in incidents if zone_id is None or i["location"]["zone_id"] == zone_id]

    def supervisor_on_duty(self) -> str:
        return next(
            m.id for m in self.sut.config.on_duty(utc_now()) if m.role.value == "supervisor"
        )

    def resolve_all(self, zone_id: str) -> None:
        """Limpieza: resuelve lo que quede abierto en una zona para no contaminar otros tests."""
        for incident in self.active_incidents(zone_id):
            self.resolve(incident["incident_id"], self.supervisor_on_duty())
        wait_until(lambda: not self.active_incidents(zone_id), timeout=10, what="zone cleanup")

    def caregivers(self, staff_ids: list[str]) -> list[Caregiver]:
        return [Caregiver(self.sut, staff_id) for staff_id in staff_ids]


def wait_until(condition: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


# --- Sistema con Docker Compose ----------------------------------------------------------


@dataclass
class ComposeSystem:
    mqtt_host: str = os.environ.get("E2E_MQTT_HOST", "localhost")
    mqtt_port: int = int(os.environ.get("E2E_MQTT_PORT", "1883"))
    backend_url: str = os.environ.get("E2E_BACKEND_URL", "http://localhost:8000")
    config: SystemConfig = field(
        default_factory=lambda: load_system_config(CONFIG_DIR, escalation_file=TEST_ESCALATION)
    )

    def wait_ready(self) -> None:
        def ready() -> bool:
            try:
                return bool(
                    httpx.get(f"{self.backend_url}/health", timeout=2).json()["mqtt_connected"]
                )
            except (httpx.HTTPError, ValueError):
                return False

        wait_until(ready, timeout=60, what=f"backend at {self.backend_url} (¿está levantado?)")

    def restart_orchestrator(self) -> None:
        subprocess.run(
            ["docker", "compose", "-p", COMPOSE_PROJECT, *COMPOSE_FILES, "restart", "orchestrator"],
            cwd=REPO_ROOT,
            check=True,
        )
        subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                COMPOSE_PROJECT,
                *COMPOSE_FILES,
                "up",
                "--wait",
                "orchestrator",
            ],
            cwd=REPO_ROOT,
            check=True,
        )


# --- Sistema en proceso (sin Docker) -----------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class InProcessSystem:
    def __init__(self) -> None:
        self.mqtt_host = "127.0.0.1"
        self.mqtt_port = _free_port()
        http_port = _free_port()
        self.backend_url = f"http://127.0.0.1:{http_port}"
        self.config = load_system_config(CONFIG_DIR, escalation_file=TEST_ESCALATION)
        self._http_port = http_port
        self._loop = (
            asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        )
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._orchestrator: Any = None
        self._orchestrator_task: asyncio.Task[None] | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._broker: Any = None
        self._server: Any = None
        from orchestrator.store import MemoryIncidentStore

        # El mismo almacén sobrevive a los "reinicios" del orquestador, como haría Postgres.
        self._store = MemoryIncidentStore()

    def _call(self, coro: Any, timeout: float = 30) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def start(self) -> None:
        self._thread.start()
        self._call(self._start())
        wait_until(lambda: self._orchestrator.connected, timeout=20, what="orchestrator")
        ComposeSystem.wait_ready(self)  # type: ignore[arg-type]

    async def _start(self) -> None:
        import uvicorn
        from amqtt.broker import Broker
        from backend.app import create_app
        from backend.settings import BackendSettings

        self._broker = Broker(
            {
                "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{self.mqtt_port}"}},
                "plugins": {
                    "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}
                },
            }
        )
        await self._broker.start()
        self._start_orchestrator()
        app = create_app(
            BackendSettings(mqtt_host=self.mqtt_host, mqtt_port=self.mqtt_port), self.config
        )
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self._http_port, log_level="warning")
        )
        self._tasks.append(asyncio.create_task(self._server.serve()))

    def _start_orchestrator(self) -> None:
        from orchestrator.service import OrchestratorService
        from orchestrator.settings import OrchestratorSettings

        settings = OrchestratorSettings(
            mqtt_host=self.mqtt_host,
            mqtt_port=self.mqtt_port,
            store="memory",
            config_dir=CONFIG_DIR,
            escalation_config=TEST_ESCALATION,
            tick_interval_s=0.2,
        )
        self._orchestrator = OrchestratorService(settings, self.config, self._store)
        self._orchestrator_task = asyncio.create_task(self._orchestrator.run())

    def restart_orchestrator(self) -> None:
        async def restart() -> None:
            assert self._orchestrator_task is not None
            self._orchestrator_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._orchestrator_task
            self._start_orchestrator()

        self._call(restart())
        wait_until(lambda: self._orchestrator.connected, timeout=20, what="orchestrator restart")

    def stop(self) -> None:
        async def stop() -> None:
            if self._server is not None:
                self._server.should_exit = True
            if self._orchestrator_task is not None:
                self._orchestrator_task.cancel()
            await asyncio.gather(*self._tasks, self._orchestrator_task, return_exceptions=True)
            if self._broker is not None:
                await self._broker.shutdown()

        with contextlib.suppress(Exception):
            self._call(stop())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)


@contextlib.contextmanager
def system_under_test() -> Iterator[SystemUnderTest]:
    target = os.environ.get("E2E_TARGET", "compose")
    if target == "compose":
        compose = ComposeSystem()
        compose.wait_ready()
        yield compose
    elif target == "inprocess":
        inprocess = InProcessSystem()
        try:
            inprocess.start()
            yield inprocess
        finally:
            inprocess.stop()
    else:
        raise ValueError(f"unknown E2E_TARGET {target!r} (use 'compose' or 'inprocess')")
