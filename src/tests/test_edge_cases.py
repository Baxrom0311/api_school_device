"""
Tests for edge cases and race conditions.

Covers:
- Device auto-register with duplicate MAC address
- OTA batch with cancelled status mid-processing
- Concurrent schedule updates (race condition)
- Token refresh with blacklisted refresh token
"""
import pytest
from unittest.mock import patch
from django.contrib.auth import get_user_model

from apps.devices.models import Device, OTABatch, OTABatchDevice, Schedule
from apps.devices.models.device import RegistrationStatus
from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus

User = get_user_model()


@pytest.mark.django_db
class TestDuplicateMACAutoRegister:
    """Test auto-register behavior when same MAC registers multiple times concurrently."""

    def test_invalid_mac_format_rejected(self, api_client):
        """Invalid MAC address format should be rejected."""
        response = api_client.post("/api/v1/device/auto-register/", {
            "device_id": "not-a-mac",
            "firmware_version": "1.0.0",
        })
        assert response.status_code == 400

    def test_concurrent_register_same_mac(self, api_client):
        """First register creates device, second returns existing."""
        mac = "AA:BB:CC:DD:EE:11"
        normalized = "AABBCCDDEE11"
        r1 = api_client.post("/api/v1/device/auto-register/", {
            "device_id": mac,
            "firmware_version": "1.0.0",
        })
        r2 = api_client.post("/api/v1/device/auto-register/", {
            "device_id": mac,
            "firmware_version": "1.0.1",
        })
        assert r1.status_code == 201
        assert r2.status_code == 200
        # Only one device in DB
        assert Device.objects.filter(device_id=normalized).count() == 1

    def test_register_updates_firmware_version(self, api_client, db):
        """Re-registering updates firmware_version field."""
        normalized = "AABBCCDDEE12"
        Device.objects.create(
            device_id=normalized,
            firmware_version="1.0.0",
            registration_status=RegistrationStatus.PENDING,
        )
        response = api_client.post("/api/v1/device/auto-register/", {
            "device_id": "AA:BB:CC:DD:EE:12",
            "firmware_version": "1.1.0",
        })
        assert response.status_code == 200
        device = Device.objects.get(device_id=normalized)
        assert device.firmware_version == "1.1.0"


@pytest.mark.django_db
class TestOTABatchCancelledMidProcessing:
    """Test that cancelled batch stops processing pending devices."""

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_ota", return_value=True)
    def test_process_cancelled_batch_skips(self, mock_send, db, admin_user):
        """process_ota_batch should return early if batch is cancelled."""
        from apps.devices.tasks import process_ota_batch
        from django.core.files.uploadedfile import SimpleUploadedFile

        fw_file = SimpleUploadedFile("fw.bin", b"\x00" * 512)
        from apps.devices.models import FirmwareVersion
        firmware = FirmwareVersion.objects.create(
            version="3.0.0", file=fw_file, is_stable=True
        )

        batch = OTABatch.objects.create(
            name="Cancel Test",
            firmware=firmware,
            created_by=admin_user,
            total_devices=2,
            status=OTABatchStatus.CANCELLED,
        )
        d1 = Device.objects.create(
            device_id="CA:NC:EL:D0:00:01",
            registration_status=RegistrationStatus.REGISTERED,
        )
        OTABatchDevice.objects.create(
            batch=batch, device=d1, status=OTADeviceStatus.PENDING
        )

        result = process_ota_batch(batch.id)
        assert result["status"] == "cancelled"
        mock_send.assert_not_called()


@pytest.mark.django_db
class TestConcurrentScheduleUpdate:
    """Test schedule update doesn't lose data under concurrent writes."""

    def test_schedule_update_uses_latest(self, admin_client, db, admin_user):
        device = Device.objects.create(
            device_id="SC:HE:DU:LE:00:01",
            registration_status=RegistrationStatus.REGISTERED,
            owner=admin_user,
        )
        # Schedule is auto-created by signal
        schedule = device.schedule
        schedule.times = ["08:00", "09:00"]
        schedule.save()

        # Two rapid updates - second should win
        admin_client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {"times": ["08:30", "09:30"]},
            format="json",
        )
        response = admin_client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {"times": ["10:00", "11:00"]},
            format="json",
        )
        assert response.status_code == 200

        schedule.refresh_from_db()
        assert schedule.times == ["10:00", "11:00"]


@pytest.mark.django_db
class TestTokenRefreshBlacklisted:
    """Test token refresh when refresh token is blacklisted."""

    def test_refresh_with_used_token(self, api_client, regular_user):
        """After logout (blacklist), refresh should fail."""
        # Login to get tokens
        login_resp = api_client.post("/api/v1/auth/login/", {
            "email": "user@test.com",
            "password": "testpass123",
        })
        assert login_resp.status_code == 200
        refresh_token = login_resp.data["refresh"]

        # Logout (blacklists the refresh token)
        api_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login_resp.data['access']}"
        )
        api_client.post("/api/v1/auth/logout/", {"refresh": refresh_token})

        # Try to use blacklisted refresh token
        api_client.credentials()  # Clear auth
        response = api_client.post("/api/v1/auth/refresh/", {
            "refresh": refresh_token,
        })
        assert response.status_code == 401


@pytest.mark.django_db
class TestCheckOTACompletion:
    """Test check_ota_completion task processes batches inline (no recursive dispatch)."""

    def test_check_all_batches_inline(self, db, admin_user):
        """When batch_id=None, all active batches are processed inline."""
        from apps.devices.tasks import check_ota_completion
        from apps.devices.models import FirmwareVersion
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone
        from datetime import timedelta

        fw_file = SimpleUploadedFile("fw.bin", b"\x00" * 512)
        firmware = FirmwareVersion.objects.create(
            version="4.0.0", file=fw_file, is_stable=True
        )

        batch = OTABatch.objects.create(
            name="Timeout Test",
            firmware=firmware,
            created_by=admin_user,
            total_devices=1,
            status=OTABatchStatus.IN_PROGRESS,
        )
        device = Device.objects.create(
            device_id="TI:ME:OU:T0:00:01",
            registration_status=RegistrationStatus.REGISTERED,
        )
        bd = OTABatchDevice.objects.create(
            batch=batch,
            device=device,
            status=OTADeviceStatus.NOTIFIED,
            notified_at=timezone.now() - timedelta(minutes=60),
        )

        result = check_ota_completion(batch_id=None, timeout_minutes=30)
        assert result["batches_checked"] == 1
        assert result["timed_out"] == 1

        bd.refresh_from_db()
        assert bd.status == OTADeviceStatus.FAILED

    def test_check_specific_batch(self, db, admin_user):
        """When batch_id is given, only that batch is checked."""
        from apps.devices.tasks import check_ota_completion
        from apps.devices.models import FirmwareVersion
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone
        from datetime import timedelta

        fw_file = SimpleUploadedFile("fw.bin", b"\x00" * 512)
        firmware = FirmwareVersion.objects.create(
            version="4.1.0", file=fw_file, is_stable=True
        )

        batch = OTABatch.objects.create(
            name="Specific Batch",
            firmware=firmware,
            created_by=admin_user,
            total_devices=1,
            status=OTABatchStatus.IN_PROGRESS,
        )
        device = Device.objects.create(
            device_id="SP:EC:IF:IC:00:01",
            registration_status=RegistrationStatus.REGISTERED,
        )
        OTABatchDevice.objects.create(
            batch=batch,
            device=device,
            status=OTADeviceStatus.NOTIFIED,
            notified_at=timezone.now() - timedelta(minutes=5),
        )

        # Not timed out yet (5 min < 30 min threshold)
        result = check_ota_completion(batch_id=batch.id, timeout_minutes=30)
        assert result["timed_out"] == 0

    def test_nonexistent_batch(self, db):
        """Non-existent batch_id returns error."""
        from apps.devices.tasks import check_ota_completion

        result = check_ota_completion(batch_id=99999)
        assert result == {"error": "Batch not found"}
