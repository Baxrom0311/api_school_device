import pytest
from unittest.mock import patch

from apps.devices.models import Device, FirmwareVersion, OTABatch, OTABatchDevice
from apps.devices.models.device import RegistrationStatus
from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus


@pytest.fixture
def firmware(db):
    from django.core.files.uploadedfile import SimpleUploadedFile

    fw_file = SimpleUploadedFile("firmware.bin", b"\x00" * 1024, content_type="application/octet-stream")
    return FirmwareVersion.objects.create(
        version="2.0.0",
        file=fw_file,
        is_stable=True,
    )


@pytest.fixture
def ota_batch(db, firmware, admin_user):
    batch = OTABatch.objects.create(
        name="Test Batch",
        firmware=firmware,
        created_by=admin_user,
        total_devices=2,
    )
    return batch


@pytest.fixture
def devices_for_ota(db, admin_user):
    d1 = Device.objects.create(
        device_id="OT:A0:DE:V1:00:01",
        firmware_version="1.0.0",
        registration_status=RegistrationStatus.REGISTERED,
        owner=admin_user,
    )
    d2 = Device.objects.create(
        device_id="OT:A0:DE:V2:00:02",
        firmware_version="1.0.0",
        registration_status=RegistrationStatus.REGISTERED,
        owner=admin_user,
    )
    return d1, d2


@pytest.mark.django_db
class TestOTABatchCRUD:
    def test_list_batches_admin(self, admin_client, ota_batch):
        response = admin_client.get("/api/v1/ota-batches/")
        assert response.status_code == 200
        assert response.data["count"] == 1

    def test_list_batches_user_forbidden(self, user_client):
        response = user_client.get("/api/v1/ota-batches/")
        assert response.status_code == 403

    def test_create_batch(self, admin_client, firmware, devices_for_ota):
        d1, d2 = devices_for_ota
        response = admin_client.post("/api/v1/ota-batches/", {
            "name": "New Batch",
            "firmware_id": str(firmware.id),
            "device_ids": [str(d1.id), str(d2.id)],
        }, format="json")
        assert response.status_code == 201
        assert response.data["name"] == "New Batch"
        assert response.data["total_devices"] == 2

    def test_retrieve_batch(self, admin_client, ota_batch):
        response = admin_client.get(f"/api/v1/ota-batches/{ota_batch.id}/")
        assert response.status_code == 200
        assert response.data["name"] == "Test Batch"

    def test_delete_batch(self, admin_client, ota_batch):
        response = admin_client.delete(f"/api/v1/ota-batches/{ota_batch.id}/")
        assert response.status_code == 204
        assert not OTABatch.objects.filter(id=ota_batch.id).exists()


@pytest.mark.django_db
class TestOTABatchActions:
    @patch("apps.devices.tasks.process_ota_batch.delay")
    def test_start_batch(self, mock_task, admin_client, ota_batch):
        response = admin_client.post(
            f"/api/v1/ota-batches/{ota_batch.id}/action/",
            {"action": "start"},
        )
        assert response.status_code == 200
        ota_batch.refresh_from_db()
        assert ota_batch.status == OTABatchStatus.IN_PROGRESS
        mock_task.assert_called_once_with(ota_batch.id)

    def test_start_already_started(self, admin_client, ota_batch):
        ota_batch.status = OTABatchStatus.IN_PROGRESS
        ota_batch.save()
        response = admin_client.post(
            f"/api/v1/ota-batches/{ota_batch.id}/action/",
            {"action": "start"},
        )
        assert response.status_code == 400

    def test_cancel_batch(self, admin_client, ota_batch, devices_for_ota):
        d1, d2 = devices_for_ota
        OTABatchDevice.objects.create(batch=ota_batch, device=d1, status=OTADeviceStatus.PENDING)
        OTABatchDevice.objects.create(batch=ota_batch, device=d2, status=OTADeviceStatus.PENDING)

        ota_batch.status = OTABatchStatus.IN_PROGRESS
        ota_batch.save()

        response = admin_client.post(
            f"/api/v1/ota-batches/{ota_batch.id}/action/",
            {"action": "cancel"},
        )
        assert response.status_code == 200
        ota_batch.refresh_from_db()
        assert ota_batch.status == OTABatchStatus.CANCELLED
        assert OTABatchDevice.objects.filter(batch=ota_batch, status=OTADeviceStatus.SKIPPED).count() == 2

    @patch("apps.devices.tasks.process_ota_batch.delay")
    def test_retry_failed(self, mock_task, admin_client, ota_batch, devices_for_ota):
        d1, d2 = devices_for_ota
        OTABatchDevice.objects.create(batch=ota_batch, device=d1, status=OTADeviceStatus.SUCCESS)
        OTABatchDevice.objects.create(batch=ota_batch, device=d2, status=OTADeviceStatus.FAILED)

        ota_batch.status = OTABatchStatus.COMPLETED
        ota_batch.success_count = 1
        ota_batch.failure_count = 1
        ota_batch.save()

        response = admin_client.post(
            f"/api/v1/ota-batches/{ota_batch.id}/action/",
            {"action": "retry_failed"},
        )
        assert response.status_code == 200
        ota_batch.refresh_from_db()
        assert ota_batch.status == OTABatchStatus.IN_PROGRESS
        assert ota_batch.failure_count == 0
        mock_task.assert_called_once()

    def test_get_active_batches(self, admin_client, ota_batch):
        response = admin_client.get("/api/v1/ota-batches/active/")
        assert response.status_code == 200
        assert len(response.data) == 1

    def test_get_batch_devices(self, admin_client, ota_batch, devices_for_ota):
        d1, d2 = devices_for_ota
        OTABatchDevice.objects.create(batch=ota_batch, device=d1, status=OTADeviceStatus.SUCCESS)
        OTABatchDevice.objects.create(batch=ota_batch, device=d2, status=OTADeviceStatus.FAILED)

        response = admin_client.get(f"/api/v1/ota-batches/{ota_batch.id}/devices/")
        assert response.status_code == 200
        assert response.data["count"] == 2

    def test_get_batch_devices_filtered(self, admin_client, ota_batch, devices_for_ota):
        d1, d2 = devices_for_ota
        OTABatchDevice.objects.create(batch=ota_batch, device=d1, status=OTADeviceStatus.SUCCESS)
        OTABatchDevice.objects.create(batch=ota_batch, device=d2, status=OTADeviceStatus.FAILED)

        response = admin_client.get(f"/api/v1/ota-batches/{ota_batch.id}/devices/?device_status=failed")
        assert response.status_code == 200
        assert response.data["count"] == 1


@pytest.mark.django_db
class TestConcurrentOTAPrevention:
    """Test that bulk_ota rejects devices with active OTA batches."""

    def test_rejects_devices_with_active_ota(self, admin_client, firmware, devices_for_ota, ota_batch):
        d1, d2 = devices_for_ota
        # Create an active OTA batch device entry
        OTABatchDevice.objects.create(
            batch=ota_batch, device=d1, status=OTADeviceStatus.PENDING
        )
        ota_batch.status = OTABatchStatus.IN_PROGRESS
        ota_batch.save()

        response = admin_client.post("/api/v1/devices/bulk_ota/", {
            "device_ids": [d1.id],
            "firmware_id": firmware.id,
        }, format="json")

        assert response.status_code == 409
        assert "active OTA" in response.data["detail"]

    @patch("apps.devices.tasks.process_ota_batch.delay")
    def test_allows_devices_without_active_ota(self, mock_task, admin_client, firmware, devices_for_ota):
        d1, d2 = devices_for_ota
        mock_task.return_value.id = "fake-task-id"

        response = admin_client.post("/api/v1/devices/bulk_ota/", {
            "device_ids": [d1.id, d2.id],
            "firmware_id": firmware.id,
        }, format="json")

        assert response.status_code == 202
        mock_task.assert_called_once()
