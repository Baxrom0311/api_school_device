"""Tests for broadcast_emergency_command Celery task logic."""
import pytest
from unittest.mock import patch

from apps.devices.models import Device
from apps.devices.tasks import broadcast_emergency_command


@pytest.mark.django_db
class TestBroadcastEmergencyCommand:
    """Test the actual task logic (chunking, MQTT calls, return value)."""

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_to_device", return_value=True)
    def test_sends_to_all_devices(self, mock_send, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        result = broadcast_emergency_command([device.id], {"command": "cancel_emergency"})

        assert result["success"] == 1
        assert result["failed"] == 0
        assert result["total"] == 1
        mock_send.assert_called_once_with(device.device_id, {"command": "cancel_emergency"})

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_to_device", return_value=False)
    def test_counts_failures(self, mock_send, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        result = broadcast_emergency_command([device.id], {"command": "ring", "duration": 30})

        assert result["success"] == 0
        assert result["failed"] == 1
        assert result["total"] == 1

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_to_device", return_value=True)
    def test_handles_empty_device_list(self, mock_send):
        result = broadcast_emergency_command([], {"command": "cancel_emergency"})

        assert result == {"success": 0, "failed": 0, "total": 0}
        mock_send.assert_not_called()

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_to_device", return_value=True)
    def test_chunks_large_device_list(self, mock_send):
        """Verify chunking works with chunk_size parameter."""
        devices = []
        for i in range(5):
            d = Device.objects.create(
                device_id=f"CHUNK_TEST_{i}",
                status="active",
                registration_status="registered",
            )
            devices.append(d)

        ids = [d.id for d in devices]
        result = broadcast_emergency_command(ids, {"command": "lockdown", "state": True}, chunk_size=2)

        assert result["success"] == 5
        assert result["total"] == 5
        assert mock_send.call_count == 5
