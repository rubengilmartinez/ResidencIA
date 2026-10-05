"""Comprobación de salud para Docker: ``python -m orchestrator.healthcheck``.

El bucle de escalado escribe un latido en cada iteración y solo corre mientras hay
conexión MQTT. Si el latido es antiguo, el orquestador no está escalando alertas aunque
el proceso siga vivo, y el contenedor debe marcarse como no saludable.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    heartbeat = os.environ.get("HEARTBEAT_FILE")
    if not heartbeat:
        print("HEARTBEAT_FILE not set")
        return 1
    max_age_s = float(os.environ.get("HEARTBEAT_MAX_AGE_S", "15"))
    try:
        age_s = time.time() - Path(heartbeat).stat().st_mtime
    except FileNotFoundError:
        print("no heartbeat yet")
        return 1
    if age_s > max_age_s:
        print(f"heartbeat too old: {age_s:.1f} s")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
