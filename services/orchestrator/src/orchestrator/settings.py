"""Ajustes de ejecución del orquestador (variables de entorno).

La configuración de dominio (residencia, personal, escalado) está en YAML; aquí solo van
los parámetros de despliegue. Las credenciales llegan por entorno, nunca en el código.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import PositiveFloat, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_client_id: str = "orchestrator"

    # "memory" sirve para desarrollo local y pruebas sin Postgres.
    store: Literal["postgres", "memory"] = "postgres"
    database_url: SecretStr | None = None

    config_dir: Path = Path("config")
    # Permite sustituir solo el escalado (los tests e2e usan plazos cortos).
    escalation_config: Path | None = None

    tick_interval_s: PositiveFloat = 1.0
    # Eventos de la misma categoría y zona dentro de esta ventana se fusionan en un incidente.
    fusion_window_s: PositiveFloat = 120.0

    heartbeat_file: Path | None = None
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _database_required(self) -> Self:
        if self.store == "postgres" and self.database_url is None:
            raise ValueError("DATABASE_URL is required when STORE=postgres")
        return self
