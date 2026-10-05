# Orquestador

Consume todos los eventos de los módulos de IA, los fusiona en incidentes, decide prioridad y
destinatarios con reglas deterministas y gestiona el escalado. Es el **único** que modifica el
estado de un incidente. El LLM no interviene aquí.

## Cómo funciona

- **Reglas** (`rules.py`): cada tipo de evento tiene categoría, prioridad y título fijos.
  `fall_suspected` → alta; `fall_confirmed` → **siempre crítica**, diga lo que diga el módulo.
  `fall_dismissed` (falsa alarma) es una regla de *retirada*: nunca abre incidentes; un
  incidente no crítico pasa a `pending_review` (prioridad baja, sin escalado, lo cierra un
  cuidador) y uno crítico solo recibe la nota. Ver
  [docs/decisions/0006-fall-false-alarm.md](../../docs/decisions/0006-fall-false-alarm.md).
- **Fusión** (`engine.py`): eventos de la misma categoría y zona dentro de `FUSION_WINDOW_S`
  forman un único incidente. Si llega uno de más prioridad, el incidente sube de prioridad.
- **Escalado** (`engine.py`): cuidadores de la zona → cuidadores de la planta → todo el
  personal y el supervisor. Plazos en `config/escalation.yaml`, contados desde que se envía
  cada etapa; las etapas que no añaden a nadie se saltan. Ver
  [docs/decisions/0004-escalation-policy.md](../../docs/decisions/0004-escalation-policy.md).
- **Servicio** (`service.py`): MQTT con sesión persistente y QoS 1, persistencia en Postgres,
  recuperación de incidentes abiertos al reiniciar y autolimpieza de estados huérfanos.

El motor (`engine.py`) es código puro: recibe el instante actual como parámetro, así que el
escalado se prueba con un reloj simulado.

## Variables de entorno

| Variable | Por defecto | Uso |
|---|---|---|
| `MQTT_HOST`, `MQTT_PORT` | `localhost`, `1883` | Broker |
| `STORE` | `postgres` | `postgres` o `memory` (desarrollo) |
| `DATABASE_URL` | — | Obligatoria con `STORE=postgres` |
| `CONFIG_DIR` | `config` | Carpeta con los YAML |
| `ESCALATION_CONFIG` | — | Sustituye solo `escalation.yaml` (tests e2e) |
| `TICK_INTERVAL_S` | `1.0` | Periodo del bucle de escalado |
| `FUSION_WINDOW_S` | `120` | Ventana de fusión de eventos |
| `HEARTBEAT_FILE` | — | Latido para el healthcheck de Docker |
| `LOG_LEVEL` | `INFO` | |

## Ejecutarlo aislado

```bash
# Con Docker (broker y base de datos reales)
docker compose up -d --build --wait mosquitto postgres orchestrator
docker compose logs -f orchestrator

# Sin Docker, desde la raíz del repo, contra un broker en localhost:1883
STORE=memory uv run python -m orchestrator
```

## Tests

```bash
uv run pytest services/orchestrator
```
