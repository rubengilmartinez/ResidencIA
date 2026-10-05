"""Punto de entrada: ``python -m backend``."""

from __future__ import annotations

import asyncio
import sys

import uvicorn
from residencia_shared.config import load_system_config
from residencia_shared.logging import configure_logging

from backend.app import create_app
from backend.settings import BackendSettings


def main() -> None:
    settings = BackendSettings()
    configure_logging("backend", settings.log_level)
    config = load_system_config(settings.config_dir)
    app = create_app(settings, config)
    server = uvicorn.Server(
        uvicorn.Config(app, host=settings.http_host, port=settings.http_port, log_config=None)
    )
    if sys.platform == "win32":
        # aiomqtt necesita el bucle de eventos basado en select (no el Proactor de Windows).
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
