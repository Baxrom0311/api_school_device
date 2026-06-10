"""
Tests for /health/live (liveness) and /health/ready (readiness) probes.

These probes are used by container orchestrators (Kubernetes, Docker
Swarm, systemd) and by the production reverse proxy. They have a
narrower contract than /health/:

- /health/live returns 200 unconditionally if the process can answer
  HTTP. It does NOT depend on DB, Redis, MQTT, or Celery.
- /health/ready returns 200 only when DB, Redis, and Celery are all
  reachable. MQTT broker reachability is intentionally NOT in the
  readiness probe (broker outages should not cause pod restarts; the
  publisher reconnects asynchronously).
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.django_db
class TestLivenessProbe:
    """Liveness probe must always succeed if the process is alive."""

    def test_live_returns_200_with_status_alive(self, api_client):
        response = api_client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.data == {"status": "alive"}

    def test_live_does_not_require_auth(self, api_client):
        # No credentials, no headers — must still return 200.
        response = api_client.get("/api/v1/health/live")
        assert response.status_code == 200

    def test_live_does_not_call_external_services(self, api_client):
        """Liveness must not touch DB, cache, MQTT, or Celery."""
        with (
            patch("apps.shared.views.health.connection") as mock_conn,
            patch("apps.shared.views.health.cache") as mock_cache,
            patch("apps.shared.views.health.mqtt_publisher") as mock_mqtt,
        ):
            response = api_client.get("/api/v1/health/live")

        assert response.status_code == 200
        mock_conn.ensure_connection.assert_not_called()
        mock_cache.set.assert_not_called()
        mock_cache.get.assert_not_called()
        mock_mqtt.is_connected.assert_not_called()


@pytest.mark.django_db
class TestReadinessProbe:
    """Readiness probe must verify DB, Redis, and Celery."""

    def _patch_celery(self, ping_result):
        mock_celery = MagicMock()
        mock_celery.control.ping.return_value = ping_result
        return patch("celery.current_app", mock_celery)

    def test_ready_returns_200_when_all_dependencies_healthy(self, api_client):
        with (
            patch("apps.shared.views.health.cache") as mock_cache,
            self._patch_celery([{"worker1": {"ok": "pong"}}]),
        ):
            mock_cache.set.return_value = None
            mock_cache.get.return_value = "1"
            response = api_client.get("/api/v1/health/ready")
        assert response.status_code == 200
        body = response.data
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["redis"] == "ok"
        assert body["checks"]["celery"] == "ok"

    def test_ready_returns_503_when_redis_down(self, api_client):
        with (
            patch("apps.shared.views.health.cache") as mock_cache,
            self._patch_celery([{"worker1": {"ok": "pong"}}]),
        ):
            mock_cache.set.side_effect = Exception("redis unreachable")
            response = api_client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.data["status"] == "not_ready"
        assert response.data["checks"]["redis"].startswith("error")

    def test_ready_returns_503_when_no_celery_workers(self, api_client):
        with (
            patch("apps.shared.views.health.cache") as mock_cache,
            self._patch_celery([]),
        ):
            mock_cache.set.return_value = None
            mock_cache.get.return_value = "1"
            response = api_client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.data["checks"]["celery"] == "no_workers"

    def test_ready_returns_503_when_celery_unavailable(self, api_client):
        """If celery raises (e.g. broker down), check is 'unavailable'."""
        mock_celery = MagicMock()
        mock_celery.control.ping.side_effect = Exception("amqp gone")
        with (
            patch("apps.shared.views.health.cache") as mock_cache,
            patch("celery.current_app", mock_celery),
        ):
            mock_cache.set.return_value = None
            mock_cache.get.return_value = "1"
            response = api_client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.data["checks"]["celery"] == "unavailable"

    def test_ready_does_not_check_mqtt_broker(self, api_client):
        """MQTT broker outage must not flip readiness — pod stays in service."""
        with (
            patch("apps.shared.views.health.cache") as mock_cache,
            patch("apps.shared.views.health.mqtt_publisher") as mock_mqtt,
            self._patch_celery([{"worker1": {"ok": "pong"}}]),
        ):
            mock_cache.set.return_value = None
            mock_cache.get.return_value = "1"
            mock_mqtt.is_connected.return_value = False
            response = api_client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert "mqtt_broker" not in response.data["checks"]
        # The readiness handler must never touch the MQTT publisher.
        mock_mqtt.is_connected.assert_not_called()

    def test_ready_does_not_require_auth(self, api_client):
        with (
            patch("apps.shared.views.health.cache") as mock_cache,
            self._patch_celery([{"worker1": {"ok": "pong"}}]),
        ):
            mock_cache.set.return_value = None
            mock_cache.get.return_value = "1"
            response = api_client.get("/api/v1/health/ready")
        # No auth headers were sent — response should still be served.
        assert response.status_code == 200
