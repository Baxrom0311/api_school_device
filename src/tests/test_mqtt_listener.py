"""
Integration tests for MQTT listener handlers.

Tests the message handling logic (alert, bell_log, heartbeat) with mocked paho client.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from apps.devices.models.bell_log import BellLog
from apps.devices.models.device_alert import DeviceAlert


@pytest.fixture
def mqtt_listener():
    """Create MQTTListener instance without connecting."""
    from apps.devices.services.mqtt_listener import MQTTListener

    listener = MQTTListener()
    return listener


@pytest.mark.django_db
class TestMQTTAlertHandler:
    """Test _handle_alert processes panic messages correctly."""

    @patch("apps.devices.tasks.notify_panic_alert.delay")
    def test_creates_alert_record(self, mock_notify, mqtt_listener, device):
        mqtt_listener._handle_alert(device.device_id, {"type": "panic"})

        alert = DeviceAlert.objects.get(device=device)
        assert alert.alert_type == "panic"
        assert alert.resolved is False
        mock_notify.assert_called_once_with(device.device_id, "panic")

    @patch("apps.devices.tasks.notify_panic_alert.delay")
    def test_unknown_device_ignored(self, mock_notify, mqtt_listener):
        mqtt_listener._handle_alert("NONEXISTENT", {"type": "panic"})

        assert DeviceAlert.objects.count() == 0
        mock_notify.assert_not_called()


@pytest.mark.django_db
class TestMQTTBellLogHandler:
    """Test _handle_bell_log creates BellLog with rate limiting."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from django.core.cache import cache

        cache.clear()
        yield
        cache.clear()

    def test_creates_bell_log(self, mqtt_listener, device):
        mqtt_listener._handle_bell_log(device.device_id, {"duration": 5000, "source": "manual"})

        log = BellLog.objects.get(device=device)
        assert log.duration_ms == 5000
        assert log.trigger_source == "manual"

    def test_rate_limits_within_1s(self, mqtt_listener, device):
        # First log
        mqtt_listener._handle_bell_log(device.device_id, {"duration": 3000, "source": "schedule"})
        assert BellLog.objects.filter(device=device).count() == 1

        # Second log within 1s — should be ignored (cache-based rate limit)
        mqtt_listener._handle_bell_log(device.device_id, {"duration": 3000, "source": "schedule"})
        assert BellLog.objects.filter(device=device).count() == 1

    def test_unknown_device_ignored(self, mqtt_listener):
        mqtt_listener._handle_bell_log("NONEXISTENT", {"duration": 3000})
        assert BellLog.objects.count() == 0


@pytest.mark.django_db
class TestMQTTHeartbeatHandler:
    """Test heartbeat message updates device monitoring fields."""

    def test_updates_monitoring_fields(self, mqtt_listener, device):
        """Simulate on_message for heartbeat topic."""
        msg = MagicMock()
        msg.topic = f"devices/{device.device_id}/status"
        msg.payload = json.dumps({"rssi": -55, "uptime": 7200, "heap": 32000}).encode()

        mqtt_listener._on_message(None, None, msg)

        device.refresh_from_db()
        assert device.rssi == -55
        assert device.uptime_sec == 7200
        assert device.free_heap == 32000
        assert device.last_seen is not None

    def test_reactivates_inactive_device(self, mqtt_listener, device):
        device.status = "inactive"
        device.save()

        msg = MagicMock()
        msg.topic = f"devices/{device.device_id}/status"
        msg.payload = json.dumps({"rssi": -70}).encode()

        mqtt_listener._on_message(None, None, msg)

        device.refresh_from_db()
        assert device.status == "active"

    def test_resolves_offline_alerts_on_reconnect(self, mqtt_listener, device):
        """When device reconnects, unresolved offline alerts should be auto-resolved."""
        device.status = "inactive"
        device.save()

        DeviceAlert.objects.create(device=device, alert_type="offline")

        msg = MagicMock()
        msg.topic = f"devices/{device.device_id}/status"
        msg.payload = json.dumps({"rssi": -60}).encode()

        mqtt_listener._on_message(None, None, msg)

        alert = DeviceAlert.objects.get(device=device, alert_type="offline")
        assert alert.resolved is True
        assert alert.resolved_at is not None
