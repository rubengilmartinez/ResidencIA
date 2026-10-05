# 0005. Entorno de desarrollo: Docker Desktop con WSL2, fuera de OneDrive

- Estado: aceptada
- Fecha: 2026-10-05

## Contexto

- El proyecto estaba en una carpeta sincronizada con OneDrive. Con `.git`, entornos virtuales,
  pesos de modelos y datasets, la sincronización provoca bloqueos de ficheros y sube gigas.
- La GPU es una **RTX 3050 Laptop de 6 GB** (no de 4 GB como se suponía al principio).
- Windows 11 con WSL2 (Ubuntu), que ya ve la GPU.

## Decisión

Elegida por el usuario:

- Repositorio en `C:\dev\ResidencIA`, fuera de OneDrive, publicado en
  <https://github.com/rubengilmartinez/ResidencIA>.
- Contenedores con **Docker Desktop y backend WSL2**, integrado en VS Code. Docker Desktop da
  acceso a la GPU desde los contenedores a través de WSL2 sin instalar NVIDIA Container Toolkit
  en Ubuntu.
- Mientras Docker no está instalado, el cableado MQTT se prueba con el arnés en proceso
  (`E2E_TARGET=inprocess`, broker amqtt).

## Consecuencias

- Docker Desktop lee las carpetas montadas desde Windows (`./config`) más despacio que desde
  el sistema de ficheros de WSL. Para la configuración no importa. Si más adelante se montan
  datasets grandes, conviene moverlos (o el repositorio) al sistema de ficheros de WSL.
- Antes de fijar modelos hay que medir la VRAM conjunta (pose, audio, LLM) sobre los 6 GB.
