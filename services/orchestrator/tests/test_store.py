"""Tests del almacén en memoria (mismo contrato que el de Postgres).

El almacén de Postgres se prueba en los tests de extremo a extremo con Docker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

from orchestrator.engine import IncidentEngine
from orchestrator.store import MemoryIncidentStore
from residencia_shared.config import SystemConfig
from residencia_shared.events import Event

EventFactory = Callable[..., Event]


def test_memory_store_round_trip_restores_engine(
    system_config: SystemConfig, make_event: EventFactory, day: datetime
) -> None:
    async def scenario() -> None:
        store = MemoryIncidentStore()
        engine = IncidentEngine(system_config, timedelta(seconds=120))
        event = make_event(at=day)
        updates = engine.handle_event(event, day)
        await store.save(updates, event)

        assert await store.event_exists(event.event_id)
        loaded = await store.load_active_incidents()
        assert [i.incident_id for i in loaded] == [updates[0].incident.incident_id]

        restored = IncidentEngine(system_config, timedelta(seconds=120), loaded)
        assert len(restored.active_incidents) == 1

    asyncio.run(scenario())
