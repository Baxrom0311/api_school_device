"""Tests for DeviceLog viewset (admin-only, read-only)."""
import pytest

from apps.devices.models import Device
from apps.devices.models.device_log import DeviceLog, LogLevel, LogSource


@pytest.fixture
def device_with_logs(db, admin_user):
    device = Device.objects.create(
        device_id="LO:GD:EV:IC:E0:01",
        school_name="Log School",
        owner=admin_user,
    )
    DeviceLog.objects.create(
        device=device, level=LogLevel.INFO, source=LogSource.DEVICE, message="Boot OK"
    )
    DeviceLog.objects.create(
        device=device, level=LogLevel.ERROR, source=LogSource.MQTT, message="Connection lost"
    )
    DeviceLog.objects.create(
        device=device, level=LogLevel.WARNING, source=LogSource.OTA, message="OTA retry"
    )
    return device


@pytest.mark.django_db
class TestDeviceLogViewSet:
    def test_admin_can_list_logs(self, admin_client, device_with_logs):
        response = admin_client.get("/api/v1/device-logs/")
        assert response.status_code == 200
        assert response.data["count"] == 3

    def test_user_cannot_list_logs(self, user_client, device_with_logs):
        response = user_client.get("/api/v1/device-logs/")
        assert response.status_code == 403

    def test_unauthenticated_cannot_list_logs(self, api_client, device_with_logs):
        response = api_client.get("/api/v1/device-logs/")
        assert response.status_code == 401

    def test_filter_by_level(self, admin_client, device_with_logs):
        response = admin_client.get("/api/v1/device-logs/?level=error")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["message"] == "Connection lost"

    def test_filter_by_source(self, admin_client, device_with_logs):
        response = admin_client.get("/api/v1/device-logs/?source=ota")
        assert response.status_code == 200
        assert response.data["count"] == 1

    def test_filter_by_ota_source(self, admin_client, device_with_logs):
        """OTA source logs are filterable."""
        response = admin_client.get("/api/v1/device-logs/?source=mqtt")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["source"] == "mqtt"

    def test_filter_by_device(self, admin_client, device_with_logs):
        response = admin_client.get(f"/api/v1/device-logs/?device={device_with_logs.id}")
        assert response.status_code == 200
        assert response.data["count"] == 3

    def test_search_by_message(self, admin_client, device_with_logs):
        response = admin_client.get("/api/v1/device-logs/?search=Connection")
        assert response.status_code == 200
        assert response.data["count"] == 1

    def test_retrieve_single_log(self, admin_client, device_with_logs):
        log = DeviceLog.objects.first()
        response = admin_client.get(f"/api/v1/device-logs/{log.id}/")
        assert response.status_code == 200
        assert response.data["id"] == str(log.id)

    def test_cannot_create_log_via_api(self, admin_client, device_with_logs):
        response = admin_client.post("/api/v1/device-logs/", {
            "device": str(device_with_logs.id),
            "level": "info",
            "source": "device",
            "message": "Should not work",
        })
        assert response.status_code == 405

    def test_cannot_delete_log_via_api(self, admin_client, device_with_logs):
        log = DeviceLog.objects.first()
        response = admin_client.delete(f"/api/v1/device-logs/{log.id}/")
        assert response.status_code == 405

    def test_ordering_by_created_at(self, admin_client, device_with_logs):
        response = admin_client.get("/api/v1/device-logs/?ordering=-created_at")
        assert response.status_code == 200
        results = response.data["results"]
        assert len(results) == 3

    def test_filter_by_debug_level(self, admin_client, device_with_logs):
        """Verify debug level filter works after adding DEBUG choice."""
        from apps.devices.models.device_log import DeviceLog, LogLevel, LogSource
        DeviceLog.objects.create(
            device=device_with_logs, level=LogLevel.DEBUG, source=LogSource.DEVICE, message="Debug trace"
        )
        response = admin_client.get("/api/v1/device-logs/?level=debug")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["message"] == "Debug trace"
