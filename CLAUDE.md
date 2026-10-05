# CLAUDE.md — Sistema de monitorización inteligente para residencias

Este archivo define el contexto, la arquitectura y las reglas de trabajo del proyecto. Léelo entero antes de cualquier tarea y respétalo en todo momento. Si una petición entra en conflicto con lo que aquí se dice, señálalo antes de actuar.

## Tu rol

Actúas como ingeniero senior de ML y de sistemas, con experiencia en computer vision, procesamiento de audio, arquitecturas orientadas a eventos y software para entornos sanitarios. Trabajas junto a un científico e ingeniero de datos recién licenciado con buen nivel en ML, DL y CV (YOLO, PyTorch). No hace falta explicarle conceptos básicos, pero sí justificar las decisiones de diseño y señalar riesgos o alternativas cuando existan.

## Objetivo del proyecto

Construir un sistema que ayude a monitorizar y cuidar a las personas de una residencia de mayores, detectando situaciones de riesgo y haciendo llegar la información correcta al cuidador correcto en el menor tiempo posible. El resultado final es una **simulación funcional** de una residencia completa (varias plantas, habitaciones y zonas comunes) que demuestre la interconexión de todos los módulos de extremo a extremo.

Es un proyecto de portafolio con vocación realista: la calidad de ingeniería, la evaluación honesta y la reducción de falsos positivos importan más que la cantidad de funcionalidades.

## Módulos de la primera versión

1. **Detección de caídas** (visión): estimación de pose + modelo temporal sobre esqueletos. La alerta se basa en caída **más** inmovilidad posterior, para reducir falsos positivos.
2. **Petición de ayuda por voz**: palabra de activación → grabación → transcripción → evento.
3. **Eventos sonoros**: detección de gritos, golpes y llanto sin transcribir conversaciones.
4. **Cambios posturales en personas encamadas** (visión): clasificar la postura en cama y medir el tiempo acumulado en cada una para recordar los cambios de posición.
5. **Agente orquestador**: consume todos los eventos, los fusiona, decide prioridad y destinatario, y gestiona el escalado.
6. **App de cuidadores**: recepción de alertas en tiempo real y flujo de aceptación ("yo me encargo").
7. **Simulador**: web con el plano de la residencia que muestra eventos y alertas en tiempo real.

## Arquitectura

```
Cámaras / micrófonos
        │
        ▼
Módulos de IA (un contenedor por módulo, servidor on-premise)
        │  publican eventos
        ▼
Broker MQTT (Mosquitto)
        │  suscriptores: orquestador y simulador
        ▼
Agente orquestador ──► PostgreSQL (incidentes, configuración)
        │
        ▼
Backend API (REST + WebSockets) ──► App de cuidadores
```

### Principios de arquitectura (no negociables)

- **Privacidad por diseño**: el vídeo y el audio se procesan localmente y nunca salen del módulo que los analiza. Entre componentes solo viajan eventos. No se guarda vídeo ni audio salvo que se pida explícitamente para depuración, y en ese caso fuera del flujo normal.
- **El LLM nunca está en el camino crítico**. El orquestador tiene dos capas:
  - Un **motor de reglas determinista** que decide prioridad, destinatario y escalado. Una caída siempre genera una alerta crítica aunque el LLM no responda.
  - Un **LLM pequeño open-source ejecutado en local** solo para enriquecer: interpretar texto libre de las peticiones por voz, redactar mensajes y generar resúmenes de turno. Si falla, el sistema sigue funcionando. La idea inicial es partir de los pesos de un modelo pequeño de la familia **Qwen** (verifica qué versiones y tamaños están disponibles antes de elegir) y especializarlo con este enfoque:
    - **Destilación**: un modelo grande actúa como profesor para generar un dataset de ejemplos del dominio (peticiones de residentes → urgencia, categoría y mensaje para el cuidador; eventos de un turno → resumen).
    - **Ajuste fino con QLoRA** del modelo pequeño (alumno) sobre ese dataset, entrenando en Kaggle.
    - **Cuantización para inferencia** (por ejemplo GGUF o AWQ a 4 bits) para que quepa en la RTX 3050 junto a los modelos de visión y audio, manteniendo en lo posible su capacidad y velocidad.
    - Es una línea de investigación abierta: compara tamaños de modelo y niveles de cuantización midiendo calidad en tareas del dominio, latencia y consumo de VRAM antes de fijar una decisión. Mientras no esté listo, una API externa puede servir como sustituto temporal.
- **Desacoplamiento**: los módulos no se conocen entre sí. Solo publican eventos con el esquema común.
- **Los cuidadores no se suscriben a MQTT**. MQTT es un bus interno. Las alertas llegan a la app a través del backend, después de pasar por el orquestador.

### Temas MQTT

Formato: `residencia/{planta}/{zona}/{modulo}`

Ejemplos: `residencia/p1/hab_12/caidas`, `residencia/p1/hab_05/postura`, `residencia/p0/comedor/audio`, `residencia/p0/comedor/voz`.

Valores de `{modulo}`: `caidas`, `postura`, `audio`, `voz`.

Bus interno entre orquestador y backend (fuera de `residencia/`; ningún módulo de IA lo usa). Ver `docs/decisions/0002`:

- `sistema/alertas/{incident_id}`: estado completo del incidente en cada cambio (QoS 1, retenido). Solo publica el orquestador, que es el único que modifica incidentes.
- `sistema/acciones`: acciones de los cuidadores (aceptar, resolver) que reenvía el backend.

### Esquema común de eventos

Todos los módulos publican este formato. Los campos comunes son obligatorios; `payload` es específico de cada módulo.

```json
{
  "event_id": "evt_8f3a2c",
  "timestamp": "2026-10-02T03:14:22Z",
  "source": "fall_detector",
  "event_type": "fall_confirmed",
  "location": { "floor_id": "p1", "zone_id": "hab_12", "zone_type": "room" },
  "confidence": 0.91,
  "severity_hint": "critical",
  "payload": { "immobile_seconds": 18 }
}
```

- `timestamp` siempre en UTC con formato ISO 8601.
- `severity_hint` es una sugerencia del módulo; la prioridad final la decide el orquestador.
- `location.floor_id` debe coincidir con la planta del tema MQTT y con la configuración; el orquestador descarta los eventos incoherentes.
- El detector de caídas publica dos eventos: `fall_suspected` al detectar la caída (prioridad alta) y `fall_confirmed` tras comprobar la inmovilidad (siempre crítica). El orquestador los fusiona en un solo incidente. Ver `docs/decisions/0003`.
- Define el esquema una sola vez como modelo Pydantic en un paquete compartido (`shared/`) y reutilízalo en todos los servicios. No dupliques definiciones.

### Residencia de ejemplo

- 2 plantas, 8 habitaciones por planta (algunas con residentes encamados), pasillos.
- Zonas comunes: comedor, sala de estar, baños comunes, jardín.
- 6 cuidadores en turno de día y 2 en turno de noche, cada uno con zonas asignadas.
- Escalado (cada plazo cuenta desde que se envía la alerta de esa etapa; ver `docs/decisions/0004`):

  | Etapa | A quién se avisa | Plazo normal | Plazo crítico |
  |---|---|---|---|
  | 1 | Cuidadores responsables de la zona | 30 s | 10 s |
  | 2 | Todos los cuidadores de la planta | 60 s | 30 s |
  | 3 | Todo el personal de turno y el supervisor | sin plazo: activa hasta que alguien acepte | |

  Los avisos son acumulativos, una etapa que no añade a nadie nuevo se salta y aceptar detiene el escalado (gana la primera aceptación).
- Toda esta información vive en ficheros de configuración (YAML), nunca en el código.

## Stack tecnológico

- **Python 3.11** con **FastAPI** para módulos y backend. Monorepo con **workspace de uv** (`uv.lock` único; cada servicio se instala con `uv sync --package`). Ver `docs/decisions/0001`.
- **Mosquitto** como broker MQTT.
- **PostgreSQL** para incidentes y configuración.
- **Docker Compose** para levantar todo el sistema, con **Docker Desktop y backend WSL2**, integrado en VS Code.
- Repositorio: <https://github.com/rubengilmartinez/ResidencIA> (en local, en `C:\dev\ResidencIA`, fuera de OneDrive).
- **App de cuidadores**: Flutter o React Native, o una PWA en React que comparta tecnología con el simulador. Decisión pendiente: no la tomes por tu cuenta, propón opciones cuando llegue el momento.
- **Simulador**: aplicación web con el plano de la residencia actualizado en tiempo real.

## Restricciones de hardware

- **Desarrollo e inferencia en local** con una GPU de portátil **RTX 3050 Laptop de 6 GB** de VRAM. Ten esto presente en cada decisión de modelo.
  - Prioriza variantes ligeras (nano/small) y exporta a ONNX o TensorRT en FP16.
  - Para caídas bastan 10–15 fps por cámara; agrupa cámaras en lote cuando sea posible.
  - En la simulación, solo unas pocas cámaras ejecutan inferencia real; el resto reproducen eventos pregrabados.
  - Los modelos de voz pueden ir en CPU (por ejemplo faster-whisper con int8) si la GPU se queda corta.
  - El LLM local comparte la GPU con todo lo anterior: mide el consumo conjunto de VRAM y, si no cabe, valora ejecutarlo en CPU o reducir su tamaño, ya que no está en el camino crítico.
- **Entrenamiento en Kaggle** (GPUs T4/P100, cuota semanal limitada). Los notebooks de entrenamiento deben ser autocontenidos, reanudables desde checkpoint y separar la extracción de poses (costosa, se hace una vez y se guarda) del entrenamiento del clasificador (ligero).
- El entorno es Windows 11: los contenedores con GPU van por WSL2. Docker Desktop expone la GPU a los contenedores sin instalar NVIDIA Container Toolkit en Ubuntu.

## Fase actual: detector de caídas

Es el módulo más crítico y por el que empezamos. Objetivo: un detector robusto que **minimice los falsos positivos** sin sacrificar la detección de caídas reales.

Líneas de trabajo:
- **Modelo de pose**: partimos de YOLO pose, pero hay que comparar alternativas (RTMPose y otras) en precisión y velocidad sobre la RTX 3050 antes de decidir.
- **Datasets**: búsqueda exhaustiva de datasets públicos de caídas y actividades de la vida diaria. Para cada uno, documentar: número de caídas y de actividades de control, puntos de vista de cámara, perfil de los sujetos y licencia.
- **Generalización**: el objetivo es invarianza a apariencia, posición, escala y, sobre todo, punto de vista.
  - Normaliza los esqueletos (centrar en la cadera, escalar por la longitud del torso).
  - Usa aumento de datos con rotaciones de los esqueletos para simular distintas posiciones de cámara (en residencias suelen ser altas y en ángulo).
  - Evalúa **entre datasets**: entrena con unos y prueba con otros no vistos. No reportes solo métricas dentro del mismo dataset.
- **Falsos positivos**: incluye actividades difíciles parecidas a caídas (tumbarse en la cama, sentarse de golpe, agacharse, recoger algo del suelo) y repórtalas por separado.
- **Limitación conocida**: la mayoría de caídas en datasets públicos las simulan actores jóvenes; las personas mayores caen distinto. Documenta esta limitación en los resultados.
- **Métricas**: sensibilidad, especificidad, falsos positivos por hora de vídeo de actividad normal y latencia de detección. La precisión global sola no es suficiente.

## Forma de trabajar

- **Planifica antes de programar**. En cualquier tarea no trivial, presenta primero un plan breve (qué vas a hacer, qué ficheros tocarás, cómo lo verificarás) y espera confirmación.
- **Desarrollo vertical**: prioriza tener un flujo completo de extremo a extremo funcionando, aunque cada parte sea básica, antes de perfeccionar un módulo aislado.
- **No tomes decisiones de arquitectura por tu cuenta**. Si algo de este documento parece mejorable, propón el cambio y explica por qué, pero no lo apliques sin aprobación.
- **Verifica lo que haces**: ejecuta los tests y comprueba que el código funciona antes de darlo por terminado. Si no puedes verificar algo, dilo claramente.
- **Sé honesto con los resultados**: no infles métricas, señala el sobreajuste y los casos de fallo. En un sistema de cuidado de personas, un resultado optimista y falso es peor que uno modesto y real.
- Si una información (por ejemplo, el rendimiento de un modelo o las características de un dataset) puede haber cambiado o no estás seguro, búscala o indícalo en lugar de suponer.

## Convenciones de código

- Python 3.11+, tipado en todas las funciones, Pydantic para modelos de datos.
- Formateo y linting con `ruff`; tests con `pytest`.
- Configuración mediante variables de entorno y ficheros YAML; nunca credenciales en el código.
- Logging estructurado (JSON) en todos los servicios.
- Nombres de código, variables y commits en inglés; documentación y comentarios explicativos en español.
- Cada servicio tiene su propio `Dockerfile` y `README.md` con cómo ejecutarlo y probarlo de forma aislada.

## Estructura del repositorio (propuesta inicial)

```
.
├── CLAUDE.md
├── docker-compose.yml
├── docker-compose.test.yml  # plazos cortos para los tests de extremo a extremo
├── config/              # residencia, zonas, cuidadores, turnos, escalado (YAML)
├── infra/mosquitto/     # configuración del broker
├── shared/              # esquema de eventos y utilidades comunes
├── services/
│   ├── fall_detector/
│   ├── posture_monitor/
│   ├── audio_events/
│   ├── voice_assistant/
│   ├── orchestrator/
│   ├── backend/
│   └── event_player/    # reproduce escenarios de eventos pregrabados
├── apps/
│   ├── caregiver_app/
│   └── simulator/
├── ml/
│   ├── notebooks/       # entrenamiento en Kaggle
│   ├── datasets/        # scripts de descarga y preprocesado (no los datos)
│   └── experiments/     # resultados y comparativas
├── tests/e2e/           # pruebas del sistema completo (Docker o en proceso)
└── docs/                # decisiones de arquitectura y resultados
```

Registra cada decisión relevante de arquitectura o de modelo en `docs/decisions/` con el contexto, las alternativas consideradas y el motivo de la elección.
