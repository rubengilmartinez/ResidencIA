# Backend

Puente entre el bus interno y la app de cuidadores. **No decide nada** sobre los incidentes:
refleja el estado que publica el orquestador y le reenvía las acciones de los cuidadores.

## API

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Estado y conexión con el bus (`mqtt_connected`) |
| `GET` | `/incidents` | Incidentes activos, por prioridad y antigüedad |
| `GET` | `/incidents/{id}` | Un incidente |
| `GET` | `/staff/{staff_id}/incidents` | Incidentes activos de un cuidador |
| `POST` | `/incidents/{id}/accept` | "Yo me encargo". Cuerpo: `{"staff_id": "..."}`. Responde 202 |
| `POST` | `/incidents/{id}/resolve` | Cierra el incidente. Responde 202 |
| `WS` | `/ws/{staff_id}` | Alertas en tiempo real del cuidador |

Las acciones responden **202**: el resultado lo decide el orquestador y llega por WebSocket.
Si dos cuidadores aceptan a la vez, gana el primero que procesa el orquestador; el segundo ve
en su WebSocket quién se ha encargado. Códigos de error: 404 (incidente o cuidador
desconocido), 409 (ya aceptado), 503 (bus no disponible).

Mensajes del WebSocket:

```json
{"type": "snapshot", "data": [<Incident>, ...]}
{"type": "incident_update", "data": <IncidentUpdate>}
{"type": "incident_removed", "data": {"incident_id": "inc_..."}}
```

Cada incidente lleva `version`: el cliente debe quedarse con la más alta.

**Limitación conocida:** no hay autenticación; el `staff_id` se confía al cliente. Es aceptable
en la simulación local, no en un despliegue real.

Documentación interactiva: `http://localhost:8000/docs`.

## Ejecutarlo aislado

```bash
docker compose up -d --build --wait mosquitto backend
# o sin Docker, desde la raíz del repo y con un broker en localhost:1883:
uv run python -m backend
```

## Tests

```bash
uv run pytest services/backend
```
