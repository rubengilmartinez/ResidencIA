# residencia-shared

Contratos comunes a todos los servicios. Es la **única** definición de cada uno; ningún
servicio los duplica.

| Módulo | Contenido |
|---|---|
| `events.py` | Esquema común de eventos (`Event`, `Location`, enumerados). Estricto: campos extra prohibidos, UTC obligatorio, el tipo de evento debe corresponder a su módulo de origen. |
| `topics.py` | Temas MQTT: `residencia/{planta}/{zona}/{modulo}` para eventos y `sistema/...` para el bus interno. Construcción, análisis y comprobación de coherencia evento/tema. |
| `internal.py` | Mensajes entre orquestador y backend: estado de incidente (`Incident`, `IncidentUpdate`) y acciones de cuidadores (`CaregiverAction`). |
| `config.py` | Modelos y carga de `config/*.yaml`, con validaciones cruzadas (zonas cubiertas en cada turno, turnos sin huecos, supervisor por turno...). |
| `logging.py` | Logging estructurado en JSON, una línea por registro. |

## Añadir un tipo de evento

1. Añádelo a `EventType` y a `EVENT_TYPE_SOURCE` en `events.py`.
2. Añade su regla en `services/orchestrator/src/orchestrator/rules.py`.
3. Los tests que comprueban que todo tipo tiene origen y regla fallarán hasta completar ambos pasos.

## Tests

```bash
uv run pytest shared
```
