# 0002. Orquestador y backend se comunican por temas MQTT internos

- Estado: aceptada
- Fecha: 2026-10-05

## Contexto

El CLAUDE.md fija el recorrido de una alerta (módulos → MQTT → orquestador → backend → app),
pero no cómo se comunican orquestador y backend en ambos sentidos: alertas hacia la app y
acciones de los cuidadores ("yo me encargo") de vuelta al orquestador.

## Alternativas

1. **Temas MQTT internos fuera de `residencia/`.** El orquestador es el único que escribe el
   estado de los incidentes.
2. **REST del orquestador al backend; el backend escribe las aceptaciones en Postgres.** Dos
   escritores sobre el mismo incidente: carreras si dos cuidadores aceptan a la vez.
3. **Orquestador dentro del proceso del backend.** Más simple, pero un fallo de la API afecta
   al motor de alertas.

## Decisión

Opción 1, elegida por el usuario:

- `sistema/alertas/{incident_id}`: el orquestador publica el estado completo del incidente en
  cada cambio (QoS 1, **retenido**). Al conectarse, el backend recibe el estado de todos los
  incidentes activos sin necesidad de otro protocolo. Al resolverse, el orquestador publica el
  estado final y después un retenido vacío para borrarlo del broker.
- `sistema/acciones`: el backend publica las acciones de los cuidadores (QoS 1). El
  orquestador las procesa de una en una; la primera aceptación gana.

Detalle añadido al implementar: el tema de alertas lleva el id del incidente
(`sistema/alertas/{id}` en lugar de `sistema/alertas`) para poder usar un mensaje retenido por
incidente.

## Consecuencias

- Un solo escritor: no hay carreras entre aceptaciones simultáneas.
- Cada incidente lleva `version`; el backend descarta duplicados y mensajes desordenados.
- Sesiones persistentes (`clean_session=False`) en orquestador y backend: si uno cae, el broker
  le guarda los mensajes QoS 1 pendientes.
- Si el backend tiene un incidente que el orquestador no conoce (retenido huérfano), al
  intentar aceptarlo el orquestador borra el retenido y la app lo retira.
- Las acciones REST responden 202 (aceptada para proceso); el resultado llega por WebSocket.
- Limitación conocida: el bus no tiene autenticación (solo se expone en 127.0.0.1). Antes de un
  despliegue real hacen falta usuarios por servicio, ACL por tema y TLS.
