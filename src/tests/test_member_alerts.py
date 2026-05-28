"""Tests for member alerts endpoint and consecutive RTC drift detection."""
import json
import pytest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from django.utils import timezone

from apps.devices.models import Device
from apps.devices.models.device_alert import DeviceAlert
from apps.devices.tasks import check_rtc_consecutive_drift


@pytest.mark.django_db
class TestMyAlertsEndpoint:
    """Test GET /api/v1/member/alerts/ endpoint."""

    def test_returns_unresolved_alerts_for_user_devices(self, user_client, user_device):
        DeviceAlert.objects.create(device=user_device, alert_type="rtc_drift")
        DeviceAlert.objects.create(device=user_device, alert_type="offline", resolved=True, resolved_at=timezone.now())

        resp = user_client.get("/api/v1/member/alerts/")

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["alert_type"] == "rtc_drift"

    def test_alert_includes_message_and_device_name(self, user_client, user_device):
        DeviceAlert.objects.create(device=user_device, alert_type="rtc_battery_dead")

        resp = user_client.get("/api/v1/member/alerts/")

        assert resp.status_code == 200
        alert = resp.data["results"][0]
        assert alert["message"] == "🔋 RTC batareykasini almashtiring!"
        assert alert["device_name"] == user_device.school_name
        assert alert["device_id"] == user_device.device_id

    def test_does_not_return_other_users_alerts(self, user_client, device):
        # device is owned by admin_user, not regular_user
        DeviceAlert.objects.create(device=device, alert_type="rtc_drift")

        resp = user_client.get("/api/v1/member/alerts/")

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 0

    def test_unauthenticated_returns_401(self, api_client):
        resp = api_client.get("/api/v1/member/alerts/")
        assert resp.status_code == 401


@pytest.mark.django_db
class TestCheckRTCConsecutiveDrift:
    """Test check_rtc_consecutive_drift task."""

    def test_increments_counter_for_drifting_devices(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.rtc_drift_sec = 400  # > 300s threshold
        device.rtc_consecutive_drift_days = 1
        device.save()

        check_rtc_consecutive_drift(drift_threshold_sec=300)

        device.refresh_from_db()
        assert device.rtc_consecutive_drift_days == 2

    def test_resets_counter_for_non_drifting_devices(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.rtc_drift_sec = 10  # < 300s
        device.rtc_consecutive_drift_days = 2
        device.save()

        check_rtc_consecutive_drift(drift_threshold_sec=300)

        device.refresh_from_db()
        assert device.rtc_consecutive_drift_days == 0

    def test_marks_battery_dead_after_3_days(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.rtc_drift_sec = 600
        device.rtc_consecutive_drift_days = 2  # will become 3 after increment
        device.rtc_battery_status = "low"
        device.save()

        result = check_rtc_consecutive_drift(drift_threshold_sec=300)

        device.refresh_from_db()
        assert device.rtc_battery_status == "dead"
        assert result["newly_dead"] == 1
        assert DeviceAlert.objects.filter(device=device, alert_type="rtc_battery_dead", resolved=False).exists()

    def test_does_not_mark_already_dead(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.rtc_drift_sec = 600
        device.rtc_consecutive_drift_days = 5
        device.rtc_battery_status = "dead"
        device.save()

        result = check_rtc_consecutive_drift(drift_threshold_sec=300)

        # Already dead, should not be in newly_dead
        assert result["newly_dead"] == 0


@pytest.mark.django_db
class TestMQTTListenerConsecutiveDrift:
    """Test MQTT listener increments consecutive drift on rtc_drift alert."""

    def test_increments_consecutive_days_on_large_drift(self):
        from apps.devices.services.mqtt_listener import MQTTListener

        device = Device.objects.create(
            device_id="DRIFT_TEST_01",
            school_name="Drift School",
            rtc_consecutive_drift_days=1,
        )
        listener = MQTTListener()
        listener._handle_alert(device.device_id, {"type": "rtc_drift", "drift_sec": 400, "battery_status": "low"})

        device.refresh_from_db()
        assert device.rtc_consecutive_drift_days == 2

    def test_marks_dead_on_third_consecutive(self):
        from apps.devices.services.mqtt_listener import MQTTListener

        device = Device.objects.create(
            device_id="DRIFT_TEST_02",
            school_name="Drift School",
            rtc_consecutive_drift_days=2,
            rtc_battery_status="low",
        )
        listener = MQTTListener()
        listener._handle_alert(device.device_id, {"type": "rtc_drift", "drift_sec": 500, "battery_status": "low"})

        device.refresh_from_db()
        assert device.rtc_battery_status == "dead"
        assert DeviceAlert.objects.filter(device=device, alert_type="rtc_battery_dead", resolved=False).exists()

    def test_heartbeat_rtc_ok_resets_counter(self):
        from apps.devices.services.mqtt_listener import MQTTListener

        device = Device.objects.create(
            device_id="DRIFT_TEST_03",
            school_name="Drift School",
            rtc_consecutive_drift_days=2,
            rtc_battery_status="low",
        )
        listener = MQTTListener()

        msg = MagicMock()
        msg.topic = f"devices/{device.device_id}/status"
        msg.payload = json.dumps({"rssi": -50, "rtc_ok": True}).encode()
        listener._on_message(None, None, msg)

        device.refresh_from_db()
        assert device.rtc_consecutive_drift_days == 0
        assert device.rtc_battery_status == "ok"
