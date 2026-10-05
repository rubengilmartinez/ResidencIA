# 0001. Monorepo Python con workspace de uv

- Estado: aceptada
- Fecha: 2026-10-05

## Contexto

Varios servicios Python (orquestador, backend, módulos de IA, reproductor de eventos) deben
compartir una única definición del esquema de eventos y de la configuración (`shared/`), y cada
servicio debe poder construirse en su propia imagen Docker con solo sus dependencias.

## Alternativas

1. **pip + instalaciones editables + requirements por servicio.** Sin lockfile común; las
   versiones pueden divergir entre servicios y entre desarrollo y Docker.
2. **Poetry.** Soporte de monorepo menos directo; más lento.
3. **Workspace de uv.** Un `uv.lock` para todo el repositorio, `shared/` como dependencia
   local de cada servicio y `uv sync --package <servicio>` para instalar solo lo necesario.

## Decisión

Workspace de uv (opción 3), elegida por el usuario. La raíz es un proyecto virtual con el grupo
`dev` (todos los paquetes en modo editable, pytest, ruff); cada servicio es un miembro con su
`pyproject.toml`. Python 3.11, con el intérprete gestionado por uv (`.python-version`).

## Consecuencias

- Versiones idénticas en desarrollo, tests e imágenes Docker (`uv sync --frozen`).
- Las imágenes se construyen con el contexto en la raíz del repo (necesitan `shared/` y
  `uv.lock`).
- Un único lockfile significa que una dependencia de desarrollo puede restringir las versiones
  de producción. Por eso `amqtt` (broker de pruebas, que fija `websockets==15.0.1`) no está en
  el lock: se añade solo al ejecutar con `uv run --with amqtt`.
- Los módulos de IA con dependencias pesadas (PyTorch, ONNX Runtime con GPU) serán miembros del
  mismo workspace; si sus dependencias chocan con las del resto, se valorará sacarlos a su
  propio proyecto y lockfile.
