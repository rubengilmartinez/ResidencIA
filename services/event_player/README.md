# Reproductor de eventos

Publica escenarios de eventos pregrabados en MQTT, con el mismo esquema y los mismos temas que
un módulo de IA real. En la simulación, solo unas pocas cámaras ejecutan inferencia real; el
resto de zonas se alimentan con este reproductor.

## Escenarios

Ficheros YAML en `scenarios/`. Cada paso indica su instante relativo, tipo de evento y zona;
la planta, el tipo de zona y el módulo de origen se deducen de la configuración:

```yaml
name: fall_confirmed_hab_12
description: Caída sospechada y confirmada 12 s después.
steps:
  - { at_s: 0, event_type: fall_suspected, zone_id: hab_12, confidence: 0.84, severity_hint: high }
  - at_s: 12
    event_type: fall_confirmed
    zone_id: hab_12
    confidence: 0.91
    severity_hint: critical
    payload: { immobile_seconds: 10 }
```

`event_id` es opcional; fijarlo permite reproducir entregas duplicadas.

## Uso

```bash
# Con Docker
docker compose run --rm event_player /scenarios/fall_suspected_comedor.yaml

# Sin Docker, desde la raíz del repo (broker en localhost:1883)
uv run python -m event_player services/event_player/scenarios/fall_confirmed_hab_12.yaml --speed 2
```

## Tests

```bash
uv run pytest services/event_player
```
