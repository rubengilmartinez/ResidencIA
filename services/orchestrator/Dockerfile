# syntax=docker/dockerfile:1
# Se construye desde la raíz del repositorio, porque necesita shared/ y uv.lock:
#   docker build -f services/orchestrator/Dockerfile -t residencia-orchestrator .

FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY . .
# Instala solo este servicio y sus dependencias (versiones fijadas por uv.lock).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package residencia-orchestrator

FROM python:3.11-slim
RUN useradd --system --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER app
WORKDIR /app
CMD ["python", "-m", "orchestrator"]
