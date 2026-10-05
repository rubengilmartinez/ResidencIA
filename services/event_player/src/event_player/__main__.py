"""CLI: ``python -m event_player escenario.yaml [--speed 2] [--host localhost]``."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from residencia_shared.config import RESIDENCE_FILE, ResidenceConfig, load_yaml
from residencia_shared.logging import configure_logging

from event_player.player import MqttPublisher, play
from event_player.scenario import load_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce escenarios de eventos en MQTT.")
    parser.add_argument("scenarios", nargs="+", type=Path, help="ficheros YAML de escenario")
    parser.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    parser.add_argument(
        "--config-dir", type=Path, default=Path(os.environ.get("CONFIG_DIR", "config"))
    )
    parser.add_argument("--speed", type=float, default=1.0, help="factor de velocidad")
    args = parser.parse_args()

    configure_logging("event_player", os.environ.get("LOG_LEVEL", "INFO"))
    residence = ResidenceConfig.model_validate(load_yaml(args.config_dir / RESIDENCE_FILE))
    with MqttPublisher(args.host, args.port) as publisher:
        for path in args.scenarios:
            play(load_scenario(path), residence, publisher, speed=args.speed)


if __name__ == "__main__":
    main()
