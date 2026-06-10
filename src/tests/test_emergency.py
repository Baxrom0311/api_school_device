"""
Tests for Emergency endpoints: ring-all, lockdown, cancel, alert filtering.
Updated for async Celery-based broadcast and rate limiting.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.devices.models.device_alert import DeviceAlert


@pytest.fixture(autouse=True)
def clear_rate_limit_cache():
    """Clear rate limit cache between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestEmergencyRingAll:
    """Test POST /api/v1/admin/emergency/ring-all/"""

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_ring_all_queues_to_active_devices(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        resp = admin_client.post("/api/v1/admin/emergency/ring-all/", {"duration": 30})

        assert resp.status_code == 202
        assert resp.data["queued"] >= 1
        mock_task.assert_called_once()
        assert DeviceAlert.objects.filter(alert_type="emergency_ring").exists()

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_ring_all_caps_duration_at_60(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        resp = admin_client.post("/api/v1/admin/emergency/ring-all/", {"duration": 999})

        assert resp.status_code == 202
        call_payload = mock_task.call_args[0][1]
        assert call_payload["duration"] == 60

    def test_ring_all_invalid_duration_returns_400(self, admin_client):
        resp = admin_client.post("/api/v1/admin/emergency/ring-all/", {"duration": "abc"})
        assert resp.status_code == 400

    def test_ring_all_requires_admin(self, user_client):
        resp = user_client.post("/api/v1/admin/emergency/ring-all/")
        assert resp.status_code == 403

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_ring_all_rate_limited(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        resp1 = admin_client.post("/api/v1/admin/emergency/ring-all/", {"duration": 5})
        assert resp1.status_code == 202

        resp2 = admin_client.post("/api/v1/admin/emergency/ring-all/", {"duration": 5})
        assert resp2.status_code == 429
        assert "retry_after" in resp2.data


@pytest.mark.django_db
class TestEmergencyLockdown:
    """Test POST /api/v1/admin/emergency/lockdown/"""

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_lockdown_queues_to_active_devices(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        resp = admin_client.post("/api/v1/admin/emergency/lockdown/", {"state": True})

        assert resp.status_code == 202
        assert resp.data["queued"] >= 1
        mock_task.assert_called_once()
        assert DeviceAlert.objects.filter(alert_type="lockdown").exists()

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_lockdown_string_false_sends_false(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        resp = admin_client.post("/api/v1/admin/emergency/lockdown/", {"state": "false"})

        assert resp.status_code == 202
        call_payload = mock_task.call_args[0][1]
        assert call_payload["state"] is False

    def test_lockdown_requires_admin(self, user_client):
        resp = user_client.post("/api/v1/admin/emergency/lockdown/")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestEmergencyCancel:
    """Test POST /api/v1/admin/emergency/cancel/"""

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_cancel_resolves_alerts(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        # Create unresolved alerts
        DeviceAlert.objects.create(device=device, alert_type="panic")
        DeviceAlert.objects.create(alert_type="emergency_ring")

        resp = admin_client.post("/api/v1/admin/emergency/cancel/")

        assert resp.status_code == 200
        assert resp.data["resolved_alerts"] == 2
        assert DeviceAlert.objects.filter(resolved=False).count() == 0
        mock_task.assert_called_once_with([device.id], {"command": "cancel_emergency"})

    def test_cancel_requires_admin(self, user_client):
        resp = user_client.post("/api/v1/admin/emergency/cancel/")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestEmergencyAlertList:
    """Test GET /api/v1/admin/emergency/"""

    def test_list_alerts(self, admin_client, device):
        DeviceAlert.objects.create(device=device, alert_type="panic")
        DeviceAlert.objects.create(alert_type="lockdown")

        resp = admin_client.get("/api/v1/admin/emergency/")

        assert resp.status_code == 200
        assert resp.data["count"] == 2

    def test_filter_by_alert_type(self, admin_client, device):
        DeviceAlert.objects.create(device=device, alert_type="panic")
        DeviceAlert.objects.create(alert_type="lockdown")
        DeviceAlert.objects.create(alert_type="offline")

        resp = admin_client.get("/api/v1/admin/emergency/?alert_type=panic")
        assert resp.status_code == 200
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["alert_type"] == "panic"

    def test_filter_by_resolved(self, admin_client, device):
        DeviceAlert.objects.create(device=device, alert_type="panic", resolved=False)
        DeviceAlert.objects.create(alert_type="lockdown", resolved=True, resolved_at=timezone.now())

        resp = admin_client.get("/api/v1/admin/emergency/?resolved=false")
        assert resp.status_code == 200
        assert resp.data["count"] == 1

    def test_list_requires_admin(self, user_client):
        resp = user_client.get("/api/v1/admin/emergency/")
        assert resp.status_code == 403
