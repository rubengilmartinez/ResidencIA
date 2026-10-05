# 0006. Falsa alarma del detector de caídas

- Estado: aceptada
- Fecha: 2026-10-06
- Completa: [0003](0003-event-schema-floor-and-two-stage-fall.md) (que dejaba esta cuestión
  pendiente)

## Contexto

El detector publica `fall_suspected` en cuanto ve una posible caída y `fall_confirmed` si la
persona sigue inmóvil. Faltaba decidir qué ocurre si la sospecha no se confirma porque la
persona se levanta: hasta ahora el incidente quedaba abierto en prioridad alta y seguía
escalando hasta que alguien lo atendía.

Hay un matiz de seguridad: el detector no siempre puede distinguir entre "no hubo caída"
(la persona se sentó de golpe) y "se cayó y se levantó sola". Una persona mayor que se levanta
tras una caída puede estar lesionada, y lo habitual es revisarla igualmente.

## Alternativas

1. **Cerrar el incidente automáticamente** como falsa alarma. Menos carga para los
   cuidadores, pero una caída real con recuperación nadie la revisaría.
2. **Detener el escalado y pedir revisión.** El incidente baja a prioridad baja, deja de
   escalar y queda visible para quienes ya fueron avisados hasta que un cuidador lo cierra.
3. Para una caída **ya confirmada**: (a) que la falsa alarma solo informe, o (b) que también la
   rebaje.

## Decisión

Elegidas por el usuario: **2** y **3a**.

- El detector publica **`fall_dismissed`** (payload con el motivo, p. ej.
  `{"reason": "person_recovered"}`).
- La regla de `fall_dismissed` es de tipo *retirada*: **nunca abre un incidente**. Se aplica al
  incidente de caída de la misma zona dentro de la ventana de fusión; si no hay ninguno, se
  registra y se ignora.
- Sobre un incidente **no crítico**:
  - Si estaba abierto, pasa al estado nuevo **`pending_review`**: prioridad baja, sin
    escalado y con el mensaje "El detector indica que la persona se ha levantado.
    Compruébalo cuando puedas".
  - Si ya estaba aceptado, sigue aceptado y baja a prioridad baja.
  - En ambos casos lo cierra un cuidador. Un incidente en `pending_review` se puede aceptar y
    resolver como cualquier otro.
- Sobre un incidente **crítico** (caída confirmada, hubo inmovilidad en el suelo) **solo se
  informa**: sigue crítico y escalando, y el mensaje añade que la persona se ha levantado.
  Así se mantiene la regla del CLAUDE.md de que una caída confirmada siempre genera alerta
  crítica.
- Si después de una falsa alarma llega otra alerta de más prioridad en la misma zona (por
  ejemplo `fall_confirmed`), el incidente **vuelve a escalar**, con el plazo contado desde el
  inicio de la etapa en curso (regla 3 de la [0004](0004-escalation-policy.md)).

## Consecuencias

- Menos alarmas: las falsas alarmas dejan de escalar a planta y a todo el personal, pero
  ninguna posible caída queda sin revisar.
- Las falsas alarmas quedan registradas (motivo `dismissed` en el historial). Servirá para
  medir los falsos positivos del detector en funcionamiento, no solo con datasets.
- La app de cuidadores tendrá que distinguir `pending_review` ("revisar cuando puedas") de
  una alerta activa.
- El detector necesita una lógica de "recuperación" (la persona vuelve a estar de pie o
  sentada con normalidad tras la sospecha). Se diseñará y evaluará con el resto del detector.
