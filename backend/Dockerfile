# syntax=docker/dockerfile:1.7

# ---------- Builder: install deps into a virtualenv ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -e ".[dev]"

# ---------- Runtime image ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash betedge

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=betedge:betedge src ./src
COPY --chown=betedge:betedge alembic.ini ./
COPY --chown=betedge:betedge alembic ./alembic
COPY --chown=betedge:betedge tests ./tests

USER betedge

EXPOSE 8000

# uvicorn is installed via fastapi[standard]
CMD ["uvicorn", "betedge.main:app", "--host", "0.0.0.0", "--port", "8000"]
