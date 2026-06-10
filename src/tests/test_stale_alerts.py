"""Tests for stale device offline alerts and cleanup_bell_logs task."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.devices.models.bell_log import BellLog
from apps.devices.models.device_alert import DeviceAlert
from apps.devices.tasks import auto_clear_silence, cleanup_bell_logs, detect_stale_devices


@pytest.mark.django_db
class TestDetectStaleDevicesAlerts:
    """Test that detect_stale_devices creates offline alerts."""

    def test_creates_offline_alert_for_stale_device(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.last_seen = timezone.now() - timedelta(hours=48)
        device.save()

        result = detect_stale_devices(threshold_hours=24)

        assert result["marked_inactive"] == 1
        alert = DeviceAlert.objects.get(device=device, alert_type="offline")
        assert alert.resolved is False

    def test_no_alert_for_recent_device(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.last_seen = timezone.now() - timedelta(hours=1)
        device.save()

        detect_stale_devices(threshold_hours=24)

        assert not DeviceAlert.objects.filter(device=device, alert_type="offline").exists()

    def test_marks_stale_device_with_null_last_seen(self, device):
        """Devices that never sent a heartbeat (last_seen=None) and were created long ago."""
        device.status = "active"
        device.registration_status = "registered"
        device.last_seen = None
        device.created_at = timezone.now() - timedelta(hours=48)
        device.save(update_fields=["status", "registration_status", "last_seen", "created_at"])

        result = detect_stale_devices(threshold_hours=24)

        assert result["marked_inactive"] == 1
        assert DeviceAlert.objects.filter(device=device, alert_type="offline").exists()


@pytest.mark.django_db
class TestCleanupBellLogs:
    """Test cleanup_bell_logs task."""

    def test_deletes_old_bell_logs(self, device):
        now = timezone.now()
        # Old log (40 days ago)
        BellLog.objects.create(
            device=device, rang_at=now - timedelta(days=40), duration_ms=3000, trigger_source="schedule"
        )
        # Recent log (5 days ago)
        BellLog.objects.create(
            device=device, rang_at=now - timedelta(days=5), duration_ms=3000, trigger_source="manual"
        )

        result = cleanup_bell_logs(retention_days=30)

        assert result["deleted"] == 1
        assert BellLog.objects.count() == 1
        assert BellLog.objects.first().trigger_source == "manual"

    def test_no_deletion_when_all_recent(self, device):
        now = timezone.now()
        BellLog.objects.create(
            device=device, rang_at=now - timedelta(days=5), duration_ms=3000, trigger_source="schedule"
        )

        result = cleanup_bell_logs(retention_days=30)

        assert result["deleted"] == 0
        assert BellLog.objects.count() == 1


@pytest.mark.django_db
class TestAutoClearSilence:
    """Test auto_clear_silence task clears silence at end of day."""

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_sends_silent_false_to_active_devices(self, mock_broadcast, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        result = auto_clear_silence()

        assert result["cleared"] >= 1
        mock_broadcast.assert_called_once_with([device.id], {"command": "silent", "state": False})

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_skips_inactive_devices(self, mock_broadcast, device):
        device.status = "inactive"
        device.save()

        result = auto_clear_silence()

        assert result["cleared"] == 0
        mock_broadcast.assert_not_called()
