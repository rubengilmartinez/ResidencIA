"""Fixtures comunes a los tests de todos los paquetes.

Los tests usan la configuración real de ``config/``: así, si alguien rompe un YAML, falla
la batería de tests y no el sistema en marcha.

Instantes de referencia (Europe/Madrid es UTC+2 en octubre de 2026):
- ``night``: 2026-10-02 03:14:22 UTC = 05:14 hora local, turno de noche.
- ``day``:   2026-10-02 10:00:00 UTC = 12:00 hora local, turno de día.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from residencia_shared.config import (
    ESCALATION_FILE,
    RESIDENCE_FILE,
    STAFF_FILE,
    SystemConfig,
    load_system_config,
    load_yaml,
)
from residencia_shared.events import Event, EventType, Severity

REPO_ROOT = Path(__file__).parent
CONFIG_DIR = REPO_ROOT / "config"

EventFactory = Callable[..., Event]


@pytest.fixture(scope="session")
def config_dir() -> Path:
    return CONFIG_DIR


@pytest.fixture(scope="session")
def system_config() -> SystemConfig:
    return load_system_config(CONFIG_DIR)


@pytest.fixture(scope="session")
def _raw_config() -> dict[str, dict[str, Any]]:
    return {
        "residence": load_yaml(CONFIG_DIR / RESIDENCE_FILE),
        "staff": load_yaml(CONFIG_DIR / STAFF_FILE),
        "escalation": load_yaml(CONFIG_DIR / ESCALATION_FILE),
    }


@pytest.fixture
def raw_config(_raw_config: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Copia editable de los YAML reales, para probar que la validación detecta errores."""
    return copy.deepcopy(_raw_config)


@pytest.fixture
def night() -> datetime:
    return datetime(2026, 10, 2, 3, 14, 22, tzinfo=UTC)


@pytest.fixture
def day() -> datetime:
    return datetime(2026, 10, 2, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def make_event(system_config: SystemConfig) -> EventFactory:
    def _make(
        event_type: EventType = EventType.FALL_SUSPECTED,
        zone_id: str = "hab_12",
        *,
        at: datetime,
        event_id: str | None = None,
        payload: dict[str, Any] | None = None,
        confidence: float = 0.9,
        severity_hint: Severity = Severity.HIGH,
    ) -> Event:
        return Event.create(
            event_type=event_type,
            location=system_config.residence.location(zone_id),
            confidence=confidence,
            severity_hint=severity_hint,
            payload=payload,
            timestamp=at,
            event_id=event_id,
        )

    return _make
