# syntax=docker/dockerfile:1.2
ARG PYTHON_VERSION=3.11

# ============================================================
# STAGE 1: Builder - Install Dependencies
# ============================================================
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install dependencies
COPY ./requirements.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ============================================================
# STAGE 2: Production App
# ============================================================
FROM python:${PYTHON_VERSION}-slim AS app

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy and set permissions for celery worker start script
COPY ./deployments/compose/backend/celery/worker/start /start-celeryworker
RUN sed -i 's/\r$//g' /start-celeryworker && chmod +x /start-celeryworker

# Copy and set permissions for celery beat start script
COPY ./deployments/compose/backend/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /start-celerybeat && chmod +x /start-celerybeat

# Copy and set permissions for flower start script
COPY ./deployments/compose/backend/celery/flower/start /start-flower
RUN sed -i 's/\r$//g' /start-flower && chmod +x /start-flower

# Copy and set permissions for mqtt listener start script
COPY ./deployments/compose/backend/mqtt/start /start-mqtt-listener
RUN sed -i 's/\r$//g' /start-mqtt-listener && chmod +x /start-mqtt-listener

# Copy and set permissions for entrypoint script
COPY ./deployments/compose/backend/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint && chmod +x /entrypoint

# Copy and set permissions for start script
COPY ./deployments/compose/backend/start /start
RUN sed -i 's/\r$//g' /start && chmod +x /start

# Copy application code
COPY src/. /app/

# Create non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup appuser \
    && chown -R appuser:appgroup /app

# Set proper permissions
RUN chgrp -R 0 /app && chmod -R g=u /app

EXPOSE 8000

ENTRYPOINT ["/entrypoint"]