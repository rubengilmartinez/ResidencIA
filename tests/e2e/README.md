# Tests de extremo a extremo

Comprueban el flujo completo: evento → MQTT → orquestador → backend → WebSocket del cuidador →
aceptación por REST → fin del escalado. Usan plazos de escalado cortos
([config/escalation.yaml](config/escalation.yaml)) y no dependen de la hora: los destinatarios
esperados se calculan con la misma configuración que el orquestador.

| Test | Qué comprueba |
|---|---|
| `test_fall_reaches_caregiver_and_accept_stops_escalation` | Alerta al cuidador de la zona, subida de prioridad al confirmarse, aceptación, ausencia de escalado posterior y resolución |
| `test_unattended_critical_fall_escalates_on_schedule` | Etapas y plazos de escalado (reloj del servidor y llegada al cliente) y latencia de entrega < 1 s |
| `test_simultaneous_accepts_first_one_wins` | Dos aceptaciones seguidas: gana la primera |
| `test_duplicate_delivery_creates_a_single_incident` | Un evento entregado dos veces crea un solo incidente |
| `test_malformed_messages_are_dropped_and_service_keeps_working` | Mensajes corruptos o incoherentes se descartan y el servicio sigue funcionando |
| `test_false_alarm_stops_escalation_and_asks_for_review` | Una falsa alarma del detector detiene el escalado y deja el incidente pendiente de revisión |
| `test_orchestrator_restart_resumes_open_incidents` | Tras reiniciar el orquestador, el incidente abierto sigue escalando |

## Contra el sistema real (Docker)

```bash
cp .env.example .env    # si no existe
docker compose -p residencia-test -f docker-compose.yml -f docker-compose.test.yml up -d --build --wait
uv run pytest -m e2e
docker compose -p residencia-test -f docker-compose.yml -f docker-compose.test.yml down -v
```

`down -v` borra los volúmenes de la prueba (base de datos y broker) para empezar limpio la
próxima vez.

## Sin Docker (en proceso)

Levanta un broker MQTT en Python (amqtt), el orquestador con almacén en memoria y el backend en
un hilo del propio pytest. Sirve para comprobar el cableado MQTT en Windows sin Docker, pero
**no** prueba Postgres, Mosquitto ni los Dockerfiles.

```bash
E2E_TARGET=inprocess uv run --with amqtt pytest -m e2e
```

`amqtt` se añade solo para esta ejecución (`--with`) y no entra en `uv.lock`, porque fija
`websockets==15.0.1` y arrastraría esa versión a la imagen del backend.
