"""Persistencia de incidentes.

PostgreSQL guarda el estado actual de cada incidente, los eventos que lo originaron y el
historial completo de cambios (auditoría y, más adelante, resúmenes de turno). Al
reiniciar, el orquestador recupera los incidentes no resueltos y el escalado continúa.

El orquestador es el único servicio que escribe en estas tablas.
"""

from __future__ import annotations

import logging
from typing import Protocol

import psycopg
from residencia_shared.events import Event
from residencia_shared.internal import Incident, IncidentStatus, IncidentUpdate

logger = logging.getLogger(__name__)


class IncidentStore(Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def load_active_incidents(self) -> list[Incident]: ...
    async def event_exists(self, event_id: str) -> bool: ...
    async def save(self, updates: list[IncidentUpdate], event: Event | None = None) -> None: ...


class MemoryIncidentStore:
    """Almacén en memoria para desarrollo local y pruebas (se pierde al reiniciar)."""

    def __init__(self) -> None:
        self.incidents: dict[str, Incident] = {}
        self.events: dict[str, Event] = {}
        self.updates: list[IncidentUpdate] = []

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def load_active_incidents(self) -> list[Incident]:
        return [
            inc.model_copy(deep=True)
            for inc in self.incidents.values()
            if inc.status is not IncidentStatus.RESOLVED
        ]

    async def event_exists(self, event_id: str) -> bool:
        return event_id in self.events

    async def save(self, updates: list[IncidentUpdate], event: Event | None = None) -> None:
        for update in updates:
            self.incidents[update.incident.incident_id] = update.incident
            self.updates.append(update)
        if event is not None:
            self.events[event.event_id] = event


SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    priority    TEXT NOT NULL,
    category    TEXT NOT NULL,
    floor_id    TEXT NOT NULL,
    zone_id     TEXT NOT NULL,
    version     INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    data        JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS incidents_status_idx ON incidents (status);

CREATE TABLE IF NOT EXISTS incident_events (
    event_id    TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents (incident_id),
    received_at TIMESTAMPTZ NOT NULL,
    event       JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS incident_updates (
    message_id  TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents (incident_id),
    at          TIMESTAMPTZ NOT NULL,
    reason      TEXT NOT NULL,
    version     INTEGER NOT NULL,
    data        JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS incident_updates_incident_idx ON incident_updates (incident_id);
"""

_UPSERT_INCIDENT = """
INSERT INTO incidents (incident_id, status, priority, category, floor_id, zone_id, version,
                       created_at, updated_at, data)
VALUES (%(incident_id)s, %(status)s, %(priority)s, %(category)s, %(floor_id)s, %(zone_id)s,
        %(version)s, %(created_at)s, %(updated_at)s, %(data)s::jsonb)
ON CONFLICT (incident_id) DO UPDATE SET
    status = EXCLUDED.status, priority = EXCLUDED.priority, version = EXCLUDED.version,
    updated_at = EXCLUDED.updated_at, data = EXCLUDED.data
WHERE incidents.version < EXCLUDED.version
"""

_INSERT_UPDATE = """
INSERT INTO incident_updates (message_id, incident_id, at, reason, version, data)
VALUES (%(message_id)s, %(incident_id)s, %(at)s, %(reason)s, %(version)s, %(data)s::jsonb)
ON CONFLICT (message_id) DO NOTHING
"""

_INSERT_EVENT = """
INSERT INTO incident_events (event_id, incident_id, received_at, event)
VALUES (%(event_id)s, %(incident_id)s, %(received_at)s, %(event)s::jsonb)
ON CONFLICT (event_id) DO NOTHING
"""


class PostgresIncidentStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: psycopg.AsyncConnection | None = None

    async def open(self) -> None:
        conn = await self._connection()
        async with conn.transaction():
            await conn.execute(SCHEMA)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _connection(self) -> psycopg.AsyncConnection:
        # Reconexión perezosa: si Postgres se reinicia, la siguiente operación reconecta.
        if self._conn is None or self._conn.closed or self._conn.broken:
            self._conn = await psycopg.AsyncConnection.connect(self._dsn, autocommit=True)
        return self._conn

    async def load_active_incidents(self) -> list[Incident]:
        conn = await self._connection()
        cur = await conn.execute(
            "SELECT data FROM incidents WHERE status <> %s", (IncidentStatus.RESOLVED.value,)
        )
        return [Incident.model_validate(row[0]) for row in await cur.fetchall()]

    async def event_exists(self, event_id: str) -> bool:
        conn = await self._connection()
        cur = await conn.execute("SELECT 1 FROM incident_events WHERE event_id = %s", (event_id,))
        return await cur.fetchone() is not None

    async def save(self, updates: list[IncidentUpdate], event: Event | None = None) -> None:
        if not updates:
            return
        conn = await self._connection()
        async with conn.transaction():
            for update in updates:
                inc = update.incident
                await conn.execute(
                    _UPSERT_INCIDENT,
                    {
                        "incident_id": inc.incident_id,
                        "status": inc.status.value,
                        "priority": inc.priority.value,
                        "category": inc.category,
                        "floor_id": inc.location.floor_id,
                        "zone_id": inc.location.zone_id,
                        "version": inc.version,
                        "created_at": inc.created_at,
                        "updated_at": inc.updated_at,
                        "data": inc.model_dump_json(),
                    },
                )
                await conn.execute(
                    _INSERT_UPDATE,
                    {
                        "message_id": update.message_id,
                        "incident_id": inc.incident_id,
                        "at": update.timestamp,
                        "reason": update.reason.value,
                        "version": inc.version,
                        "data": update.model_dump_json(),
                    },
                )
            if event is not None:
                await conn.execute(
                    _INSERT_EVENT,
                    {
                        "event_id": event.event_id,
                        "incident_id": updates[0].incident.incident_id,
                        "received_at": updates[0].timestamp,
                        "event": event.model_dump_json(),
                    },
                )
