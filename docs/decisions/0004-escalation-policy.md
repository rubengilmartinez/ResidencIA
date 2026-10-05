# 0004. Política de escalado

- Estado: aceptada
- Fecha: 2026-10-05

## Contexto

El CLAUDE.md describía el escalado de forma ambigua: no quedaba claro desde cuándo contaba cada
plazo ni si las alertas críticas acortaban también la segunda etapa.

## Decisión

Confirmada por el usuario. Cada plazo cuenta **desde que se envía la alerta de esa etapa**:

| Etapa | A quién se avisa | Plazo normal | Plazo crítico |
|---|---|---|---|
| 1 | Cuidadores responsables de la zona en el turno actual | 30 s | 10 s |
| 2 | Todos los cuidadores de la planta | 60 s | 30 s |
| 3 | Todo el personal de turno y el supervisor | sin plazo: activa hasta que alguien acepte | |

Los valores viven en `config/escalation.yaml`.

Reglas añadidas al implementar:

1. **Los avisos son acumulativos**: quien ya fue avisado sigue recibiendo los cambios.
2. **Se salta la etapa que no añade a nadie.** De noche hay un cuidador por planta, así que la
   etapa de planta coincide con la de zona; esperar otro plazo con las mismas personas solo
   retrasaría el aviso al resto. El salto siempre adelanta el escalado, nunca lo retrasa.
3. **Si la prioridad sube** (sospecha → caída confirmada), el plazo de la etapa actual se
   recalcula con el valor crítico desde el mismo inicio de etapa. Si ya ha vencido, se escala
   en ese momento.
4. **Aceptar detiene el escalado.** Solo cuenta la primera aceptación.
5. **Un tick tardío** (p. ej. tras reiniciar el orquestador) escala una etapa cada vez, y la
   nueva etapa cuenta desde que realmente se envía.
6. La configuración se valida al arrancar: cada zona debe tener cuidador en cada turno, cada
   turno un supervisor y los turnos deben cubrir las 24 h sin huecos ni solapes. El plazo
   crítico no puede ser mayor que el normal.

## Consecuencias

- El motor de escalado es puro (recibe el instante actual) y se prueba con un reloj simulado.
- La regla 5 sigue al pie de la letra la definición acordada. Tras una caída larga del
  orquestador, un incidente que ya debería estar en la etapa 3 pasa antes por la 2. Si se
  prefiere recuperar el tiempo perdido, se puede cambiar para que cuente desde el vencimiento
  teórico.
