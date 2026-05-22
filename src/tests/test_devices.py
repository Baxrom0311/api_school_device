import pytest
from unittest.mock import patch

from apps.devices.models import Device
from apps.devices.models.device import RegistrationStatus


@pytest.mark.django_db
class TestDeviceAutoRegister:
    def test_auto_register_new_device(self, api_client):
        response = api_client.post("/api/v1/devices/auto-register/", {
            "device_id": "AA:BB:CC:DD:EE:01",
            "firmware_version": "1.0.0",
        })
        assert response.status_code == 201
        assert response.data["status"] == "pending"

        device = Device.objects.get(device_id="AABBCCDDEE01")
        assert device.registration_status == RegistrationStatus.PENDING

    def test_auto_register_existing_pending(self, api_client, db):
        Device.objects.create(
            device_id="AABBCCDDEE02",
            registration_status=RegistrationStatus.PENDING,
        )
        response = api_client.post("/api/v1/devices/auto-register/", {
            "device_id": "AA:BB:CC:DD:EE:02",
            "firmware_version": "1.1.0",
        })
        assert response.status_code == 200
        assert response.data["status"] == "pending"

    def test_auto_register_existing_registered_no_credentials(self, api_client, db):
        """Registered devices must NOT get credentials via auto-register (use /activate/ instead)."""
        Device.objects.create(
            device_id="AABBCCDDEE03",
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/devices/auto-register/", {
            "device_id": "AA:BB:CC:DD:EE:03",
            "firmware_version": "1.0.0",
        })
        assert response.status_code == 200
        assert response.data["status"] == "already_registered"
        assert response.data["credentials"] is None


@pytest.mark.django_db
class TestDeviceActivate:
    def test_activate_valid_key(self, api_client, db):
        device = Device.objects.create(
            device_id="AC:TI:VA:TE:00:01",
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/devices/activate/", {
            "api_key": device.api_key,
        })
        assert response.status_code == 200
        assert "mqtt_username" in response.data

    def test_activate_invalid_key(self, api_client):
        response = api_client.post("/api/v1/devices/activate/", {
            "api_key": "sk_invalid_key_here",
        })
        assert response.status_code == 401

    def test_activate_unregistered_device(self, api_client, db):
        device = Device.objects.create(
            device_id="UN:RE:GI:ST:00:01",
            registration_status=RegistrationStatus.PENDING,
        )
        response = api_client.post("/api/v1/devices/activate/", {
            "api_key": device.api_key,
        })
        assert response.status_code == 403


@pytest.mark.django_db
class TestDeviceClaim:
    def test_claim_unregistered_device(self, user_client, regular_user, db):
        device = Device.objects.create(
            device_id="CL:AI:ME:D0:00:01",
            registration_status=RegistrationStatus.UNREGISTERED,
        )
        response = user_client.post("/api/v1/devices/claim/", {
            "device_id": "CL:AI:ME:D0:00:01",
        })
        assert response.status_code == 200

        device.refresh_from_db()
        assert device.owner == regular_user
        assert device.registration_status == RegistrationStatus.REGISTERED

    def test_claim_already_claimed(self, user_client, db, admin_user):
        Device.objects.create(
            device_id="AL:RE:AD:YC:LA:IM",
            registration_status=RegistrationStatus.REGISTERED,
            owner=admin_user,
        )
        response = user_client.post("/api/v1/devices/claim/", {
            "device_id": "AL:RE:AD:YC:LA:IM",
        })
        assert response.status_code == 400

    def test_claim_unauthenticated(self, api_client, db):
        Device.objects.create(
            device_id="NO:AU:TH:CL:AI:M0",
            registration_status=RegistrationStatus.UNREGISTERED,
        )
        response = api_client.post("/api/v1/devices/claim/", {
            "device_id": "NO:AU:TH:CL:AI:M0",
        })
        assert response.status_code == 401


@pytest.mark.django_db
class TestDevicePermissions:
    def test_admin_sees_all_devices(self, admin_client, device, user_device):
        response = admin_client.get("/api/v1/devices/")
        assert response.status_code == 200
        assert response.data["count"] == 2

    def test_user_sees_only_own_devices(self, user_client, device, user_device):
        response = user_client.get("/api/v1/devices/")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["device_id"] == "11:22:33:44:55:66"

    def test_user_cannot_create_device(self, user_client):
        response = user_client.post("/api/v1/devices/", {
            "device_id": "NE:WD:EV:IC:E0:01",
        })
        assert response.status_code == 403

    def test_admin_can_create_device(self, admin_client):
        response = admin_client.post("/api/v1/devices/", {
            "device_id": "NE:WD:EV:IC:E0:02",
        })
        assert response.status_code == 201

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.ring", return_value=True)
    def test_admin_can_ring(self, mock_ring, admin_client, device):
        response = admin_client.post(f"/api/v1/devices/{device.id}/ring/", {
            "duration": 5,
        })
        assert response.status_code == 200

    def test_admin_can_view_stats(self, admin_client, device):
        response = admin_client.get("/api/v1/devices/stats/")
        assert response.status_code == 200
        assert "total_devices" in response.data

    def test_user_cannot_view_stats(self, user_client):
        response = user_client.get("/api/v1/devices/stats/")
        assert response.status_code == 403


@pytest.mark.django_db
class TestDeviceApprove:
    def test_approve_pending_device(self, admin_client, db):
        device = Device.objects.create(
            device_id="PE:ND:IN:GD:EV:01",
            registration_status=RegistrationStatus.PENDING,
        )
        response = admin_client.post(f"/api/v1/devices/{device.id}/approve/", {
            "school_name": "Approved School",
            "address": "123 Street",
        })
        assert response.status_code == 200

        device.refresh_from_db()
        assert device.registration_status == RegistrationStatus.REGISTERED
        assert device.school_name == "Approved School"

    def test_user_cannot_approve(self, user_client, db):
        device = Device.objects.create(
            device_id="PE:ND:IN:GD:EV:02",
            registration_status=RegistrationStatus.PENDING,
        )
        response = user_client.post(f"/api/v1/devices/{device.id}/approve/", {
            "school_name": "School",
        })
        assert response.status_code == 403


@pytest.mark.django_db
class TestDeviceEndpointsAutoRegister:
    """Tests for /api/v1/device/auto-register/ (ESP32-facing endpoint)."""

    def test_new_device_returns_pending(self, api_client):
        response = api_client.post("/api/v1/device/auto-register/", {
            "device_id": "DE:AD:BE:EF:00:01",
            "firmware_version": "1.0.0",
        })
        assert response.status_code == 201
        assert response.data["status"] == "pending"
        assert response.data["credentials"] is None

    def test_registered_device_no_credential_leak(self, api_client, db):
        """CRITICAL: registered devices must NOT get credentials via auto-register."""
        Device.objects.create(
            device_id="DEADBEEF0002",
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/device/auto-register/", {
            "device_id": "DE:AD:BE:EF:00:02",
            "firmware_version": "1.0.0",
        })
        assert response.status_code == 200
        assert response.data["status"] == "already_registered"
        assert response.data["credentials"] is None
        assert "activate" in response.data["message"].lower()

    def test_pending_device_returns_pending(self, api_client, db):
        Device.objects.create(
            device_id="DEADBEEF0003",
            registration_status=RegistrationStatus.PENDING,
        )
        response = api_client.post("/api/v1/device/auto-register/", {
            "device_id": "DE:AD:BE:EF:00:03",
            "firmware_version": "1.1.0",
        })
        assert response.status_code == 200
        assert response.data["status"] == "pending"
        assert response.data["credentials"] is None


@pytest.mark.django_db
class TestBulkOperationsAsync:
    """Tests that bulk operations return 202 and delegate to Celery."""

    @patch("apps.devices.tasks.send_bulk_ring.delay")
    def test_bulk_ring_returns_202(self, mock_delay, admin_client, device):
        mock_delay.return_value.id = "fake-task-id"
        response = admin_client.post("/api/v1/devices/bulk_ring/", {
            "device_ids": [str(device.id)],
        }, format="json")
        assert response.status_code == 202
        assert response.data["status"] == "accepted"
        mock_delay.assert_called_once_with([device.id])

    @patch("apps.devices.tasks.process_ota_batch.delay")
    def test_bulk_ota_returns_202(self, mock_delay, admin_client, device, db):
        from apps.devices.models import FirmwareVersion
        from django.core.files.base import ContentFile

        mock_delay.return_value.id = "fake-task-id"
        fw = FirmwareVersion(version="9.0.0")
        fw.file.save("v9.bin", ContentFile(b"\x00" * 100), save=False)
        fw.checksum = "abc"
        fw.save()

        device.registration_status = RegistrationStatus.REGISTERED
        device.save()

        response = admin_client.post("/api/v1/devices/bulk_ota/", {
            "device_ids": [device.id],
            "firmware_id": fw.id,
        }, format="json")
        assert response.status_code == 202
        assert response.data["status"] == "accepted"
        mock_delay.assert_called_once()
