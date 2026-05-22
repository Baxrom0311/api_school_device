"""
Tests for Celery tasks.

Covers:
- send_bulk_ring: success and partial failure
- send_bulk_restart: success and partial failure
- process_ota_batch: success, cancelled batch, completed batch, MQTT failure
- check_ota_completion: timeout marking, specific batch, all batches
- sync_pending_schedules: success and failure cases
- detect_stale_devices: marks inactive devices
- generate_daily_report: returns correct stats
"""
import pytest
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.utils import timezone

from apps.devices.models import Device, Schedule
from apps.devices.services.mqtt_publisher import MQTTPublisher
from apps.devices.tasks import (
    send_bulk_ring,
    send_bulk_restart,
    process_ota_batch,
    check_ota_completion,
    sync_pending_schedules,
    detect_stale_devices,
    generate_daily_report,
)


@pytest.fixture
def firmware(db):
    from apps.devices.models import FirmwareVersion
    from django.core.files.base import ContentFile

    fw = FirmwareVersion(version="2.0.0")
    fw.file.save("v2.0.0.bin", ContentFile(b"\x00" * 100), save=False)
    fw.checksum = "abc123"
    fw.save()
    return fw


@pytest.fixture
def ota_batch(admin_user, firmware):
    from apps.devices.models import OTABatch
    from apps.devices.models.ota_batch import OTABatchStatus

    return OTABatch.objects.create(
        name="Test Batch",
        firmware=firmware,
        created_by=admin_user,
        status=OTABatchStatus.PENDING,
        devices_per_hour=60,
    )


@pytest.fixture
def schedule_device(db, admin_user):
    """A separate device for schedule tests (no pre-existing schedule)."""
    import uuid
    return Device.objects.create(
        device_id=f"SCHED_{uuid.uuid4().hex[:8].upper()}",
        school_name="Schedule School",
        firmware_version="1.0.0",
        owner=admin_user,
    )


@pytest.mark.django_db
class TestSendBulkRing:
    """Test send_bulk_ring task."""

    @patch.object(MQTTPublisher, "ring", return_value=True)
    def test_sends_ring_to_all_devices(self, mock_ring, device):
        result = send_bulk_ring([device.id])

        assert result["success"] == 1
        assert result["failed"] == 0
        assert result["total"] == 1
        mock_ring.assert_called_once_with(device.device_id)

    @patch.object(MQTTPublisher, "ring", return_value=False)
    def test_counts_failures(self, mock_ring, device):
        result = send_bulk_ring([device.id])

        assert result["success"] == 0
        assert result["failed"] == 1

    @patch.object(MQTTPublisher, "ring", return_value=True)
    def test_empty_list(self, mock_ring):
        result = send_bulk_ring([])

        assert result["success"] == 0
        assert result["total"] == 0
        mock_ring.assert_not_called()


@pytest.mark.django_db
class TestSendBulkRestart:
    """Test send_bulk_restart task."""

    @patch.object(MQTTPublisher, "send_restart", return_value=True)
    def test_sends_restart_to_all_devices(self, mock_restart, device):
        result = send_bulk_restart([device.id])

        assert result["success"] == 1
        assert result["failed"] == 0
        assert result["total"] == 1
        mock_restart.assert_called_once_with(device.device_id)

    @patch.object(MQTTPublisher, "send_restart", return_value=False)
    def test_counts_failures(self, mock_restart, device):
        result = send_bulk_restart([device.id])

        assert result["success"] == 0
        assert result["failed"] == 1

    @patch.object(MQTTPublisher, "send_restart", return_value=True)
    def test_empty_list(self, mock_restart):
        result = send_bulk_restart([])

        assert result["success"] == 0
        assert result["total"] == 0
        mock_restart.assert_not_called()


@pytest.mark.django_db
class TestProcessOTABatch:
    """Test process_ota_batch task."""

    @patch.object(MQTTPublisher, "send_ota", return_value=True)
    def test_processes_pending_devices(self, mock_send_ota, ota_batch, device):
        from apps.devices.models import OTABatchDevice
        from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus

        OTABatchDevice.objects.create(
            batch=ota_batch, device=device, status=OTADeviceStatus.PENDING
        )

        result = process_ota_batch(ota_batch.id)

        assert result["status"] == "completed"
        ota_batch.refresh_from_db()
        assert ota_batch.status == OTABatchStatus.COMPLETED
        mock_send_ota.assert_called_once()

    def test_cancelled_batch_skipped(self, ota_batch):
        from apps.devices.models.ota_batch import OTABatchStatus

        ota_batch.status = OTABatchStatus.CANCELLED
        ota_batch.save()

        result = process_ota_batch(ota_batch.id)

        assert result["status"] == "cancelled"

    def test_completed_batch_skipped(self, ota_batch):
        from apps.devices.models.ota_batch import OTABatchStatus

        ota_batch.status = OTABatchStatus.COMPLETED
        ota_batch.save()

        result = process_ota_batch(ota_batch.id)

        assert result["status"] == "already_completed"

    def test_nonexistent_batch(self):
        result = process_ota_batch(99999)
        assert "error" in result

    @patch.object(MQTTPublisher, "send_ota", return_value=False)
    def test_mqtt_failure_marks_device_failed(self, mock_send_ota, ota_batch, device):
        from apps.devices.models import OTABatchDevice
        from apps.devices.models.ota_batch import OTADeviceStatus

        OTABatchDevice.objects.create(
            batch=ota_batch, device=device, status=OTADeviceStatus.PENDING
        )

        process_ota_batch(ota_batch.id)

        ota_dev = OTABatchDevice.objects.get(batch=ota_batch, device=device)
        assert ota_dev.status == OTADeviceStatus.FAILED
        assert ota_dev.error_message == "MQTT publish failed"


@pytest.mark.django_db
class TestCheckOTACompletion:
    """Test check_ota_completion task."""

    def test_times_out_stale_notified_devices(self, ota_batch, device):
        from apps.devices.models import OTABatchDevice
        from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus

        ota_batch.status = OTABatchStatus.IN_PROGRESS
        ota_batch.save()

        OTABatchDevice.objects.create(
            batch=ota_batch,
            device=device,
            status=OTADeviceStatus.NOTIFIED,
            notified_at=timezone.now() - timedelta(minutes=60),
        )

        result = check_ota_completion(ota_batch.id, timeout_minutes=30)

        assert result["timed_out"] == 1
        ota_dev = OTABatchDevice.objects.get(batch=ota_batch, device=device)
        assert ota_dev.status == OTADeviceStatus.FAILED
        assert "timeout" in ota_dev.error_message

    def test_does_not_timeout_recent_notifications(self, ota_batch, device):
        from apps.devices.models import OTABatchDevice
        from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus

        ota_batch.status = OTABatchStatus.IN_PROGRESS
        ota_batch.save()

        OTABatchDevice.objects.create(
            batch=ota_batch,
            device=device,
            status=OTADeviceStatus.NOTIFIED,
            notified_at=timezone.now() - timedelta(minutes=5),
        )

        result = check_ota_completion(ota_batch.id, timeout_minutes=30)

        assert result["timed_out"] == 0

    def test_check_all_batches(self, ota_batch, device):
        from apps.devices.models import OTABatchDevice
        from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus

        ota_batch.status = OTABatchStatus.IN_PROGRESS
        ota_batch.save()

        OTABatchDevice.objects.create(
            batch=ota_batch,
            device=device,
            status=OTADeviceStatus.NOTIFIED,
            notified_at=timezone.now() - timedelta(hours=2),
        )

        result = check_ota_completion(batch_id=None, timeout_minutes=30)

        assert result["batches_checked"] >= 1
        assert result["timed_out"] >= 1

    def test_nonexistent_batch(self):
        result = check_ota_completion(batch_id=99999)
        assert "error" in result


@pytest.mark.django_db
class TestSyncPendingSchedules:
    """Test sync_pending_schedules task."""

    @patch.object(MQTTPublisher, "send_schedule", return_value=True)
    def test_syncs_pending_schedules(self, mock_send, schedule_device):
        # Update the auto-created schedule
        sched = Schedule.objects.get(device=schedule_device)
        sched.times = ["08:00", "12:00"]
        sched.sync_pending = True
        sched.is_active = True
        sched.save()

        result = sync_pending_schedules()

        assert result["synced"] == 1
        assert result["failed"] == 0
        mock_send.assert_called_once_with(schedule_device.device_id, ["08:00", "12:00"])

    @patch.object(MQTTPublisher, "send_schedule", return_value=False)
    def test_mqtt_failure_counted(self, mock_send, schedule_device):
        sched = Schedule.objects.get(device=schedule_device)
        sched.times = ["08:00"]
        sched.sync_pending = True
        sched.is_active = True
        sched.save()

        result = sync_pending_schedules()

        assert result["synced"] == 0
        assert result["failed"] == 1

    @patch.object(MQTTPublisher, "send_schedule", return_value=True)
    def test_inactive_schedules_skipped(self, mock_send, schedule_device):
        sched = Schedule.objects.get(device=schedule_device)
        sched.times = ["08:00"]
        sched.sync_pending = True
        sched.is_active = False
        sched.save()

        result = sync_pending_schedules()

        assert result["synced"] == 0
        assert result["failed"] == 0
        mock_send.assert_not_called()


@pytest.mark.django_db
class TestDetectStaleDevices:
    """Test detect_stale_devices task."""

    def test_marks_stale_devices_inactive(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save(update_fields=["status", "registration_status"])
        # Bypass auto_now to set old updated_at
        Device.objects.filter(pk=device.pk).update(
            updated_at=timezone.now() - timedelta(hours=48)
        )

        result = detect_stale_devices(threshold_hours=24)

        assert result["marked_inactive"] >= 1
        device.refresh_from_db()
        assert device.status == "inactive"

    def test_recent_devices_not_affected(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save(update_fields=["status", "registration_status"])

        result = detect_stale_devices(threshold_hours=24)

        device.refresh_from_db()
        assert device.status == "active"


@pytest.mark.django_db
class TestGenerateDailyReport:
    """Test generate_daily_report task."""

    def test_returns_report_structure(self, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        result = generate_daily_report()

        assert "date" in result
        assert "total_devices" in result
        assert "registered_devices" in result
        assert "firmware_distribution" in result
        assert result["total_devices"] >= 1
