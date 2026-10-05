# 0003. Planta en la ubicación del evento y caída en dos eventos

- Estado: aceptada
- Fecha: 2026-10-05

## Contexto

1. La planta aparece en el tema MQTT (`residencia/{planta}/{zona}/{modulo}`) pero no en el
   cuerpo del evento, así que un evento no se entendía por sí solo (al guardarlo o reenviarlo
   se perdía la planta).
2. Una caída solo genera alerta crítica tras comprobar la inmovilidad posterior, lo que retrasa
   el aviso varios segundos.

## Alternativas

1. Planta: (a) añadir `floor_id` a `location`; (b) que el orquestador la deduzca de la
   configuración a partir de `zone_id`.
2. Caída: (a) un único evento `fall_detected` tras la inmovilidad; (b) dos eventos,
   `fall_suspected` al detectar la caída y `fall_confirmed` tras la inmovilidad.

## Decisión

Elegidas por el usuario: **1a** y **2b**.

- `location` = `{floor_id, zone_id, zone_type}`. El orquestador comprueba que coincide con la
  configuración y con el tema por el que llegó el evento; si no, lo descarta.
- `fall_suspected` → incidente de prioridad **alta**; `fall_confirmed` → se fusiona en el mismo
  incidente y lo sube a **crítica**. Una caída confirmada es siempre crítica,
  independientemente de `severity_hint` y `confidence`.

## Consecuencias

- El cuidador recibe aviso en cuanto se detecta la caída, sin esperar a la inmovilidad.
- Al subir a crítica se aplican los plazos críticos desde el inicio de la etapa actual, así que
  el escalado puede producirse en ese mismo instante (ver 0004).
- **Pendiente de decidir:** si el detector debe publicar algo cuando una sospecha no se
  confirma (la persona se levanta). Ahora mismo el incidente queda abierto en prioridad alta
  hasta que un cuidador lo atiende, que es la opción conservadora.
