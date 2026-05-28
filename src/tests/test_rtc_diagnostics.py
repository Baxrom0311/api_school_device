"""
Tests for RTC drift alert handling in MQTT listener and device model.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from django.utils import timezone

from apps.devices.models import Device
from apps.devices.models.device_alert import DeviceAlert


@pytest.fixture
def mqtt_listener():
    from apps.devices.services.mqtt_listener import MQTTListener
    return MQTTListener()


@pytest.mark.django_db
class TestRTCDriftAlertHandler:
    """Test _handle_alert with rtc_drift type updates device and creates alert."""

    def test_rtc_drift_low_battery(self, mqtt_listener, device):
        mqtt_listener._handle_alert(
            device.device_id, {"type": "rtc_drift", "drift_sec": 312, "battery_status": "low"}
        )

        device.refresh_from_db()
        assert device.rtc_synced is False
        assert device.rtc_battery_status == "low"
        assert device.rtc_drift_sec == 312

        alert = DeviceAlert.objects.get(device=device, alert_type="rtc_drift")
        assert alert.resolved is False

    def test_rtc_drift_dead_battery(self, mqtt_listener, device):
        mqtt_listener._handle_alert(
            device.device_id, {"type": "rtc_drift", "drift_sec": 900, "battery_status": "dead"}
        )

        device.refresh_from_db()
        assert device.rtc_battery_status == "dead"
        assert device.rtc_drift_sec == 900

        assert DeviceAlert.objects.filter(device=device, alert_type="rtc_battery_dead").exists()

    def test_rtc_drift_does_not_send_telegram(self, mqtt_listener, device):
        """RTC drift alerts don't trigger Telegram (not panic)."""
        with patch("apps.devices.tasks.notify_panic_alert.delay") as mock_notify:
            mqtt_listener._handle_alert(
                device.device_id, {"type": "rtc_drift", "drift_sec": 400, "battery_status": "low"}
            )
            mock_notify.assert_not_called()

    def test_rtc_drift_idempotent(self, mqtt_listener, device):
        """Multiple rtc_drift alerts don't create duplicate unresolved alerts."""
        mqtt_listener._handle_alert(
            device.device_id, {"type": "rtc_drift", "drift_sec": 300, "battery_status": "low"}
        )
        mqtt_listener._handle_alert(
            device.device_id, {"type": "rtc_drift", "drift_sec": 350, "battery_status": "low"}
        )

        assert DeviceAlert.objects.filter(device=device, alert_type="rtc_drift", resolved=False).count() == 1


@pytest.mark.django_db
class TestHeartbeatRTCReset:
    """Test that heartbeat with rtc_ok resets RTC battery status."""

    def test_rtc_ok_resets_battery_status(self, mqtt_listener, device):
        # Set device to bad RTC state
        Device.objects.filter(id=device.id).update(
            rtc_synced=False, rtc_battery_status="low", rtc_drift_sec=300
        )

        msg = MagicMock()
        msg.topic = f"devices/{device.device_id}/status"
        msg.payload = json.dumps({"rssi": -55, "rtc_ok": True}).encode()

        mqtt_listener._on_message(None, None, msg)

        device.refresh_from_db()
        assert device.rtc_synced is True
        assert device.rtc_battery_status == "ok"
        assert device.rtc_drift_sec is None

    def test_rtc_ok_resolves_alerts(self, mqtt_listener, device):
        """rtc_ok in heartbeat auto-resolves RTC drift and battery dead alerts."""
        DeviceAlert.objects.create(device=device, alert_type="rtc_drift", resolved=False)
        DeviceAlert.objects.create(device=device, alert_type="rtc_battery_dead", resolved=False)

        msg = MagicMock()
        msg.topic = f"devices/{device.device_id}/status"
        msg.payload = json.dumps({"rssi": -55, "rtc_ok": True}).encode()
        mqtt_listener._on_message(None, None, msg)

        assert not DeviceAlert.objects.filter(device=device, resolved=False, alert_type__in=["rtc_drift", "rtc_battery_dead"]).exists()

    def test_heartbeat_without_rtc_ok_does_not_reset(self, mqtt_listener, device):
        Device.objects.filter(id=device.id).update(
            rtc_synced=False, rtc_battery_status="low", rtc_drift_sec=300
        )

        msg = MagicMock()
        msg.topic = f"devices/{device.device_id}/status"
        msg.payload = json.dumps({"rssi": -55}).encode()

        mqtt_listener._on_message(None, None, msg)

        device.refresh_from_db()
        assert device.rtc_synced is False
        assert device.rtc_battery_status == "low"


@pytest.mark.django_db
class TestDeviceRTCBatteryStatusField:
    """Test device model rtc_battery_status field."""

    def test_default_is_ok(self, device):
        assert device.rtc_battery_status == "ok"

    def test_rtc_drift_sec_nullable(self, device):
        assert device.rtc_drift_sec is None
