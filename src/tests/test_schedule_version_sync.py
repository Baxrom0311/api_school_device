"""Tests for schedule version-based sync on device heartbeat."""

import json
from unittest.mock import MagicMock, patch

import pytest

from apps.devices.models import Device, Schedule


@pytest.mark.django_db
class TestScheduleVersionSync:
    """Test that heartbeat with schedule_version triggers sync if outdated."""

    def _make_heartbeat_msg(self, device_id, schedule_version, rssi=-50):
        msg = MagicMock()
        msg.topic = f"devices/{device_id}/status"
        msg.payload = json.dumps({"rssi": rssi, "schedule_version": schedule_version}).encode()
        return msg

    def test_pushes_schedule_when_device_version_outdated(self):
        from apps.devices.services.mqtt_listener import MQTTListener

        device = Device.objects.create(device_id="SYNC_TEST_01", school_name="Sync School")
        # Signal auto-creates schedule; update it
        Schedule.objects.filter(device=device).update(times=["08:00", "12:00"], version=3)

        listener = MQTTListener()
        msg = self._make_heartbeat_msg(device.device_id, schedule_version=1)

        with patch("apps.devices.services.mqtt_publisher.mqtt_publisher.send_schedule", return_value=True) as mock_send:
            listener._on_message(None, None, msg)

        mock_send.assert_called_once_with(device.device_id, ["08:00", "12:00"], version=3)

        schedule = Schedule.objects.get(device=device)
        assert schedule.sync_pending is False
        assert schedule.synced_at is not None

    def test_does_not_push_when_version_matches(self):
        from apps.devices.services.mqtt_listener import MQTTListener

        device = Device.objects.create(device_id="SYNC_TEST_02", school_name="Sync School")
        Schedule.objects.filter(device=device).update(times=["08:00"], version=5)

        listener = MQTTListener()
        msg = self._make_heartbeat_msg(device.device_id, schedule_version=5)

        with patch("apps.devices.services.mqtt_publisher.mqtt_publisher.send_schedule") as mock_send:
            listener._on_message(None, None, msg)

        mock_send.assert_not_called()

    def test_does_not_push_when_device_version_newer(self):
        from apps.devices.services.mqtt_listener import MQTTListener

        device = Device.objects.create(device_id="SYNC_TEST_03", school_name="Sync School")
        Schedule.objects.filter(device=device).update(times=["08:00"], version=2)

        listener = MQTTListener()
        msg = self._make_heartbeat_msg(device.device_id, schedule_version=3)

        with patch("apps.devices.services.mqtt_publisher.mqtt_publisher.send_schedule") as mock_send:
            listener._on_message(None, None, msg)

        mock_send.assert_not_called()

    def test_no_active_schedule_does_not_crash(self):
        from apps.devices.services.mqtt_listener import MQTTListener

        device = Device.objects.create(device_id="SYNC_TEST_04", school_name="No Schedule")
        Schedule.objects.filter(device=device).update(is_active=False)

        listener = MQTTListener()
        msg = self._make_heartbeat_msg(device.device_id, schedule_version=1)

        with patch("apps.devices.services.mqtt_publisher.mqtt_publisher.send_schedule") as mock_send:
            listener._on_message(None, None, msg)

        mock_send.assert_not_called()

    def test_heartbeat_without_schedule_version_skips_check(self):
        from apps.devices.services.mqtt_listener import MQTTListener

        device = Device.objects.create(device_id="SYNC_TEST_05", school_name="No Version")
        Schedule.objects.filter(device=device).update(times=["09:00"], version=2)

        listener = MQTTListener()
        msg = MagicMock()
        msg.topic = f"devices/{device.device_id}/status"
        msg.payload = json.dumps({"rssi": -60}).encode()

        with patch("apps.devices.services.mqtt_publisher.mqtt_publisher.send_schedule") as mock_send:
            listener._on_message(None, None, msg)

        mock_send.assert_not_called()
