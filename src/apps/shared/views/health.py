"""
Health check endpoints for monitoring.

/health/live  - Liveness: process is running (always 200)
/health/ready - Readiness: DB, Redis, MQTT all connected
/health/      - Full status with all checks (legacy)
"""
import logging

from django.db import connection
from django.core.cache import cache
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.services import mqtt_publisher

logger = logging.getLogger(__name__)


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

        # MQTT publisher check
        try:
            checks["mqtt_publisher"] = "ok" if mqtt_publisher.is_connected() else "disconnected"
            try:
                cb_state = mqtt_publisher._circuit_breaker.state
                if isinstance(cb_state, str):
                    checks["mqtt_circuit_breaker"] = cb_state
            except (AttributeError, TypeError):
                pass
        except Exception:
            checks["mqtt_publisher"] = "unavailable"

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

        healthy = all(v == "ok" for v in checks.values())
        status_code = 200 if healthy else 503
        return Response({"status": "healthy" if healthy else "degraded", "checks": checks}, status=status_code)
