"""Punto de entrada: ``python -m orchestrator``."""

from __future__ import annotations

import asyncio
import contextlib
import sys

from residencia_shared.config import load_system_config
from residencia_shared.logging import configure_logging

from orchestrator.service import OrchestratorService
from orchestrator.settings import OrchestratorSettings
from orchestrator.store import IncidentStore, MemoryIncidentStore, PostgresIncidentStore


def build_store(settings: OrchestratorSettings) -> IncidentStore:
    if settings.store == "memory":
        return MemoryIncidentStore()
    assert settings.database_url is not None  # garantizado por la validación de ajustes
    return PostgresIncidentStore(settings.database_url.get_secret_value())


def main() -> None:
    settings = OrchestratorSettings()
    configure_logging("orchestrator", settings.log_level)
    config = load_system_config(settings.config_dir, escalation_file=settings.escalation_config)
    service = OrchestratorService(settings, config, build_store(settings))
    if sys.platform == "win32":
        # aiomqtt y psycopg asíncrono necesitan el bucle de eventos basado en select.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(service.run())


if __name__ == "__main__":
    main()
