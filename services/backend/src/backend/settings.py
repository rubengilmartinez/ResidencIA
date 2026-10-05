"""Ajustes de ejecución del backend (variables de entorno)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_client_id: str = "backend"

    config_dir: Path = Path("config")

    # Dentro del contenedor escucha en todas las interfaces; Docker decide qué se expone.
    http_host: str = "0.0.0.0"
    http_port: int = 8000

    log_level: str = "INFO"
