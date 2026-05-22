import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.django_db
class TestHealthEndpoint:
    def test_health_returns_200_when_healthy(self, api_client):
        mock_celery = MagicMock()
        mock_celery.control.ping.return_value = [{"worker1": {"ok": "pong"}}]
        with patch("apps.shared.views.health.mqtt_publisher") as mock_mqtt, \
             patch("apps.shared.views.health.cache") as mock_cache, \
             patch("apps.shared.views.health.current_app", mock_celery, create=True), \
             patch("celery.current_app", mock_celery):
            mock_mqtt.is_connected.return_value = True
            mock_cache.set.return_value = None
            mock_cache.get.side_effect = lambda key, *a: "1" if key == "_health" else {"status": "alive"}
            response = api_client.get("/api/v1/health/")
        assert response.status_code == 200
        assert response.data["status"] == "healthy"
        assert response.data["checks"]["database"] == "ok"

    def test_health_returns_503_when_mqtt_down(self, api_client):
        mock_celery = MagicMock()
        mock_celery.control.ping.return_value = [{"worker1": {"ok": "pong"}}]
        with patch("apps.shared.views.health.mqtt_publisher") as mock_mqtt, \
             patch("apps.shared.views.health.cache") as mock_cache, \
             patch("celery.current_app", mock_celery):
            mock_mqtt.is_connected.return_value = False
            mock_cache.set.return_value = None
            mock_cache.get.side_effect = lambda key, *a: "1" if key == "_health" else {"status": "alive"}
            response = api_client.get("/api/v1/health/")
        assert response.status_code == 503
        assert response.data["status"] == "degraded"

    def test_health_no_auth_required(self, api_client):
        mock_celery = MagicMock()
        mock_celery.control.ping.return_value = [{"worker1": {"ok": "pong"}}]
        with patch("apps.shared.views.health.mqtt_publisher") as mock_mqtt, \
             patch("apps.shared.views.health.cache") as mock_cache, \
             patch("celery.current_app", mock_celery):
            mock_mqtt.is_connected.return_value = True
            mock_cache.set.return_value = None
            mock_cache.get.side_effect = lambda key, *a: "1" if key == "_health" else {"status": "alive"}
            response = api_client.get("/api/v1/health/")
        assert response.status_code == 200

    def test_health_mqtt_listener_no_heartbeat(self, api_client):
        mock_celery = MagicMock()
        mock_celery.control.ping.return_value = [{"worker1": {"ok": "pong"}}]
        with patch("apps.shared.views.health.mqtt_publisher") as mock_mqtt, \
             patch("apps.shared.views.health.cache") as mock_cache, \
             patch("celery.current_app", mock_celery):
            mock_mqtt.is_connected.return_value = True
            mock_cache.set.return_value = None
            mock_cache.get.side_effect = lambda key, *a: "1" if key == "_health" else None
            response = api_client.get("/api/v1/health/")
        assert response.status_code == 503
        assert response.data["checks"]["mqtt_listener"] == "no_heartbeat"


@pytest.mark.django_db
class TestRequestIDMiddleware:
    def test_response_has_request_id_header(self, api_client):
        with patch("apps.shared.views.health.mqtt_publisher") as mock_mqtt, \
             patch("apps.shared.views.health.cache") as mock_cache:
            mock_mqtt.is_connected.return_value = True
            mock_cache.set.return_value = None
            mock_cache.get.side_effect = lambda key, *a: "1" if key == "_health" else {"status": "alive"}
            response = api_client.get("/api/v1/health/")
        assert "X-Request-ID" in response

    def test_custom_request_id_passed_through(self, api_client):
        custom_id = "test-request-123"
        with patch("apps.shared.views.health.mqtt_publisher") as mock_mqtt, \
             patch("apps.shared.views.health.cache") as mock_cache:
            mock_mqtt.is_connected.return_value = True
            mock_cache.set.return_value = None
            mock_cache.get.side_effect = lambda key, *a: "1" if key == "_health" else {"status": "alive"}
            response = api_client.get("/api/v1/health/", HTTP_X_REQUEST_ID=custom_id)
        assert response["X-Request-ID"] == custom_id
