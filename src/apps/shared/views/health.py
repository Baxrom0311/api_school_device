"""
Health check endpoints for monitoring.

/health/live  - Liveness: process is running (always 200)
/health/ready - Readiness: DB, Redis, MQTT all connected
/health/      - Full status with all checks (legacy)
"""

import logging
import os
import socket

from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.services import mqtt_publisher

logger = logging.getLogger(__name__)


def _check_mqtt_broker_reachable(timeout: float = 1.5) -> tuple[str, str | None]:
    """
    Health probe for the MQTT broker that does NOT depend on the publisher
    singleton being warmed up. The publisher uses lazy connect so on a fresh
    process it would always report 'disconnected' even when the broker is fine.

    Strategy:
    1. Prefer the in-process publisher's reported state if it is currently
       connected (cheapest, most accurate).
    2. Otherwise, do a TCP probe against MQTT_BROKER_HOST:MQTT_BROKER_PORT.
       This confirms broker reachability without leaking credentials.

    Returns (status_string, error_message_or_None).
    Error messages never include broker host or port to avoid leaking
    deployment topology in failure responses.
    """
    # 1. Trust an already-connected publisher
    try:
        if mqtt_publisher.is_connected():
            return "ok", None
    except Exception:  # noqa: S110 — health probe deliberately swallows;
        # the publisher singleton can raise during lazy init and we just
        # want to fall through to the cheaper TCP probe below.
        logger.debug("mqtt_publisher.is_connected() raised; falling back to TCP probe", exc_info=True)

    # 2. TCP reachability probe
    host = os.getenv("MQTT_BROKER_HOST", "").strip()
    port_raw = os.getenv("MQTT_BROKER_PORT", "1883").strip()
    if not host:
        return "unconfigured", None

    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        return "misconfigured", "invalid MQTT_BROKER_PORT"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return "reachable", None
    except OSError as exc:
        # Map errno to a generic category — no host/port in the message
        return "unreachable", exc.__class__.__name__
    finally:
        try:
            sock.close()
        except OSError:
            pass


class LivenessView(APIView):
    """Liveness probe - returns 200 if process is alive."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "alive"})


class ReadinessView(APIView):
    """Readiness probe - checks DB, Redis, Celery connectivity."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {}

        # DB check
        try:
            connection.ensure_connection()
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {e}"

        # Redis check
        try:
            cache.set("_health", "1", 5)
            checks["redis"] = "ok" if cache.get("_health") == "1" else "error"
        except Exception as e:
            checks["redis"] = f"error: {e}"

        # Celery worker check (ping)
        try:
            from celery import current_app

            result = current_app.control.ping(timeout=2.0)
            checks["celery"] = "ok" if result else "no_workers"
        except Exception:
            checks["celery"] = "unavailable"

        healthy = all(v == "ok" for v in checks.values())
        status_code = 200 if healthy else 503
        return Response({"status": "ready" if healthy else "not_ready", "checks": checks}, status=status_code)


class HealthCheckView(APIView):
    """Full health check with all services."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {}

        # DB check
        try:
            connection.ensure_connection()
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {e}"

        # Redis check
        try:
            cache.set("_health", "1", 5)
            checks["redis"] = "ok" if cache.get("_health") == "1" else "error"
        except Exception as e:
            checks["redis"] = f"error: {e}"

        # MQTT broker reachability check
        # Avoid relying on the lazy publisher singleton: a freshly-started
        # process will always report 'disconnected' there even when the
        # broker is healthy. We probe TCP reachability instead.
        try:
            mqtt_status, mqtt_err = _check_mqtt_broker_reachable()
            checks["mqtt_broker"] = mqtt_status
            if mqtt_err:
                checks["mqtt_broker_error"] = mqtt_err
        except Exception:
            checks["mqtt_broker"] = "unavailable"

        # Publisher circuit breaker state (if available, informational only)
        try:
            cb_state = mqtt_publisher._circuit_breaker.state
            if isinstance(cb_state, str):
                checks["mqtt_circuit_breaker"] = cb_state
        except (AttributeError, TypeError):
            pass

        # MQTT listener check (via Redis heartbeat key)
        try:
            listener_health = cache.get("mqtt_listener:alive")
            checks["mqtt_listener"] = "ok" if listener_health else "no_heartbeat"
        except Exception:
            checks["mqtt_listener"] = "unavailable"

        # Celery worker check
        try:
            from celery import current_app

            result = current_app.control.ping(timeout=2.0)
            checks["celery"] = "ok" if result else "no_workers"
        except Exception:
            checks["celery"] = "unavailable"

        # 'reachable' (TCP probe succeeded) and 'ok' (publisher connected)
        # are both healthy values for mqtt_broker.
        def _is_healthy(key: str, value: str) -> bool:
            if key == "mqtt_broker":
                return value in {"ok", "reachable"}
            if key == "mqtt_broker_error":
                # Informational field, ignore in health calculation
                return True
            if key == "mqtt_circuit_breaker":
                # Informational field, ignore in health calculation
                return True
            return value == "ok"

        healthy = all(_is_healthy(k, v) for k, v in checks.items())
        status_code = 200 if healthy else 503
        return Response({"status": "healthy" if healthy else "degraded", "checks": checks}, status=status_code)
