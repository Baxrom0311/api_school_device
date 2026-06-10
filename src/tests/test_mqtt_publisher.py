"""
Tests for MQTT Publisher and Listener services.

Covers:
- MQTTPublisher publish, send_schedule, ring, send_ota, send_restart
- MQTTPublisher connection handling and error cases
- MQTTListener message routing and OTA status handling
"""

from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.devices.services.mqtt_publisher import MQTTConfig, MQTTPublisher


@pytest.fixture
def mqtt_config():
    return MQTTConfig(
        host="localhost",
        port=1883,
        username="test",
        password="test",
        client_id="test-publisher",
    )


@pytest.fixture
def publisher(mqtt_config):
    """Create a fresh publisher instance (bypass singleton)."""
    MQTTPublisher._instance = None
    pub = MQTTPublisher(mqtt_config)
    return pub


@pytest.mark.django_db
class TestMQTTPublisher:
    """Test MQTTPublisher command methods."""

    @patch.object(MQTTPublisher, "_get_client")
    def test_publish_success(self, mock_get_client, publisher):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.rc = 0  # MQTT_ERR_SUCCESS
        mock_client.publish.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = publisher.publish("test/topic", {"key": "value"}, qos=1)

        assert result is True
        mock_client.publish.assert_called_once_with("test/topic", '{"key": "value"}', qos=1, retain=False)

    @patch.object(MQTTPublisher, "_get_client")
    def test_publish_failure(self, mock_get_client, publisher):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.rc = 1  # Error
        mock_client.publish.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = publisher.publish("test/topic", {"key": "value"})

        assert result is False

    @patch.object(MQTTPublisher, "_get_client")
    def test_publish_exception(self, mock_get_client, publisher):
        mock_get_client.side_effect = ConnectionError("Broker down")

        result = publisher.publish("test/topic", {"data": 1})

        assert result is False

    @patch.object(MQTTPublisher, "publish")
    def test_ring_command(self, mock_publish, publisher):
        mock_publish.return_value = True

        result = publisher.ring("AABBCCDDEE01", duration=5)

        assert result is True
        mock_publish.assert_called_once_with(
            "devices/AABBCCDDEE01/command",
            {"command": "ring", "duration": 5},
            qos=0,
        )

    @patch.object(MQTTPublisher, "publish")
    def test_send_schedule(self, mock_publish, publisher):
        mock_publish.return_value = True

        result = publisher.send_schedule("DEV001", ["08:30", "09:15", "12:00"])

        assert result is True
        call_args = mock_publish.call_args
        assert call_args[0][0] == "devices/DEV001/schedule"
        payload = call_args[0][1]
        assert len(payload["entries"]) == 3
        assert payload["entries"][0] == {"hour": 8, "minute": 30, "duration": 3000, "days": 0x1F}

    @patch.object(MQTTPublisher, "publish")
    def test_send_ota(self, mock_publish, publisher):
        mock_publish.return_value = True

        result = publisher.send_ota("DEV001", "https://firmware.example.com/v2.bin")

        assert result is True
        mock_publish.assert_called_once_with(
            "devices/DEV001/command",
            {"command": "ota", "url": "https://firmware.example.com/v2.bin"},
            qos=1,
        )

    @patch.object(MQTTPublisher, "publish")
    def test_send_restart(self, mock_publish, publisher):
        mock_publish.return_value = True

        result = publisher.send_restart("DEV001")

        assert result is True
        mock_publish.assert_called_once_with(
            "devices/DEV001/command",
            {"command": "reboot"},
            qos=1,
        )

    @patch.object(MQTTPublisher, "publish")
    def test_broadcast_schedule(self, mock_publish, publisher):
        mock_publish.return_value = True

        results = publisher.broadcast_schedule(
            ["DEV001", "DEV002", "DEV003"],
            ["08:00", "12:00"],
        )

        assert results == {"DEV001": True, "DEV002": True, "DEV003": True}
        assert mock_publish.call_count == 3


@pytest.mark.django_db
class TestMQTTListenerOTAHandler:
    """Test OTA status handler in MQTT listener."""

    def test_ota_success_updates_batch(self, admin_user, device):
        from django.core.files.base import ContentFile

        from apps.devices.models import FirmwareVersion, OTABatch, OTABatchDevice
        from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus
        from apps.devices.services.mqtt_listener import OTAStatusHandler

        firmware = FirmwareVersion(version="2.0.0")
        firmware.file.save("v2.0.0.bin", ContentFile(b"\x00" * 100), save=False)
        firmware.checksum = "abc123"
        firmware.save()
        batch = OTABatch.objects.create(
            name="Test OTA",
            firmware=firmware,
            created_by=admin_user,
            status=OTABatchStatus.IN_PROGRESS,
        )
        ota_device = OTABatchDevice.objects.create(
            batch=batch,
            device=device,
            status=OTADeviceStatus.NOTIFIED,
            notified_at=timezone.now(),
        )

        OTAStatusHandler.handle(device.device_id, {"status": "success"})

        ota_device.refresh_from_db()
        batch.refresh_from_db()
        assert ota_device.status == OTADeviceStatus.SUCCESS
        assert ota_device.completed_at is not None
        assert batch.success_count == 1

    def test_ota_failure_updates_batch(self, admin_user, device):
        from django.core.files.base import ContentFile

        from apps.devices.models import FirmwareVersion, OTABatch, OTABatchDevice
        from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus
        from apps.devices.services.mqtt_listener import OTAStatusHandler

        firmware = FirmwareVersion(version="2.0.0")
        firmware.file.save("v2.0.0.bin", ContentFile(b"\x00" * 100), save=False)
        firmware.checksum = "abc123"
        firmware.save()
        batch = OTABatch.objects.create(
            name="Test OTA",
            firmware=firmware,
            created_by=admin_user,
            status=OTABatchStatus.IN_PROGRESS,
        )
        OTABatchDevice.objects.create(
            batch=batch,
            device=device,
            status=OTADeviceStatus.NOTIFIED,
            notified_at=timezone.now(),
        )

        OTAStatusHandler.handle(device.device_id, {"status": "failed", "error": "Flash error"})

        ota_dev = OTABatchDevice.objects.get(batch=batch, device=device)
        batch.refresh_from_db()
        assert ota_dev.status == OTADeviceStatus.FAILED
        assert ota_dev.error_message == "Flash error"
        assert batch.failure_count == 1

    def test_ota_unknown_device_ignored(self):
        from apps.devices.services.mqtt_listener import OTAStatusHandler

        # Should not raise
        OTAStatusHandler.handle("NONEXISTENT", {"status": "success"})

    def test_ota_no_pending_batch_ignored(self, device):
        from apps.devices.services.mqtt_listener import OTAStatusHandler

        # Should not raise when device has no pending OTA
        OTAStatusHandler.handle(device.device_id, {"status": "success"})
