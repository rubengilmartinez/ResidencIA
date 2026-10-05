# ResidencIA

Sistema de monitorización inteligente para residencias de mayores: detecta situaciones de
riesgo (caídas, peticiones de ayuda, eventos sonoros, tiempo sin cambio postural) y hace
llegar la alerta al cuidador adecuado lo antes posible, con escalado si nadie responde.

Es un proyecto de portafolio con vocación realista: el resultado final es una simulación
funcional de una residencia completa. El contexto completo, la arquitectura y las reglas de
trabajo están en [CLAUDE.md](CLAUDE.md); las decisiones, en [docs/decisions/](docs/decisions/).

## Estado

| Pieza | Estado |
|---|---|
| Esquema común de eventos, temas MQTT y configuración (`shared/`) | Base hecha y probada |
| Orquestador: reglas, fusión de eventos y escalado (`services/orchestrator/`) | Base hecha y probada |
| Backend: WebSocket para cuidadores y REST de acciones (`services/backend/`) | Base hecha y probada |
| Reproductor de eventos pregrabados (`services/event_player/`) | Base hecha y probada |
| Detector de caídas | En investigación: [inventario de datasets](docs/datasets/fall_datasets.md) |
| Postura en cama, eventos sonoros, voz, LLM local | Pendiente |
| App de cuidadores y simulador web | Pendiente (tecnología por decidir) |

## Flujo actual

```
event_player ──(residencia/{planta}/{zona}/{modulo})──► Mosquitto ──► orquestador ──► PostgreSQL
                                                                         │
                                         sistema/alertas/{incidente} ◄───┘
                                                    │
                                                    ▼
                         backend ──WebSocket──► cuidadores ──REST "yo me encargo"──► backend
                            └──────────── sistema/acciones ────────────► orquestador
```

## Puesta en marcha

Requisitos: [uv](https://docs.astral.sh/uv/) y, para el sistema completo, Docker Desktop
con WSL2.

```bash
uv sync                      # entorno de desarrollo con todos los paquetes
uv run pytest                # tests unitarios (rápidos, sin red ni esperas)
uv run ruff check . && uv run ruff format --check .
```

Sistema completo con Docker:

```bash
cp .env.example .env         # y cambia la contraseña
docker compose up -d --build --wait
docker compose run --rm event_player /scenarios/fall_confirmed_hab_12.yaml
curl http://localhost:8000/incidents
```

Tests de extremo a extremo: ver [tests/e2e/README.md](tests/e2e/README.md).

## Estructura

```
config/              residencia, personal, turnos y escalado (YAML, validado al arrancar)
shared/              contratos comunes: eventos, mensajes internos, temas, configuración, logging
services/
  orchestrator/      motor de reglas, fusión de eventos, escalado e incidentes
  backend/           API para la app de cuidadores
  event_player/      reproduce escenarios de eventos pregrabados
infra/mosquitto/     configuración del broker
tests/e2e/           pruebas del sistema completo
docs/                decisiones de arquitectura e investigación
ml/                  notebooks de entrenamiento, scripts de datasets y experimentos
```
