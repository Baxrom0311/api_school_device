"""
Tests for device claim flow (Member App user claims a device by MAC address).
"""
import pytest
from django.contrib.auth import get_user_model

from apps.devices.models import Device
from apps.devices.models.device import RegistrationStatus

User = get_user_model()


@pytest.mark.django_db
class TestDeviceClaim:
    def test_claim_unregistered_device(self, user_client, regular_user, db):
        """User can claim an unregistered device."""
        Device.objects.create(
            device_id="CL:AI:M0:00:00:01",
            registration_status=RegistrationStatus.UNREGISTERED,
        )
        response = user_client.post("/api/v1/devices/claim/", {
            "device_id": "CL:AI:M0:00:00:01",
            "device_name": "My Bell",
        })
        assert response.status_code == 200
        device = Device.objects.get(device_id="CL:AI:M0:00:00:01")
        assert device.owner == regular_user
        assert device.school_name == "My Bell"
        assert device.registration_status == RegistrationStatus.REGISTERED

    def test_claim_pending_device(self, user_client, regular_user, db):
        """User can claim a pending device (pending approval)."""
        Device.objects.create(
            device_id="CL:AI:M0:00:00:02",
            registration_status=RegistrationStatus.PENDING,
        )
        response = user_client.post("/api/v1/devices/claim/", {
            "device_id": "CL:AI:M0:00:00:02",
        })
        assert response.status_code == 200
        device = Device.objects.get(device_id="CL:AI:M0:00:00:02")
        assert device.owner == regular_user
        assert device.registration_status == RegistrationStatus.REGISTERED

    def test_claim_already_registered_device_rejected(self, user_client, db):
        """Cannot claim a device that is already registered."""
        Device.objects.create(
            device_id="CL:AI:M0:00:00:03",
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = user_client.post("/api/v1/devices/claim/", {
            "device_id": "CL:AI:M0:00:00:03",
        })
        assert response.status_code == 400

    def test_claim_nonexistent_device(self, user_client, db):
        """Cannot claim a device that doesn't exist."""
        response = user_client.post("/api/v1/devices/claim/", {
            "device_id": "NO:SU:CH:DE:VI:CE",
        })
        assert response.status_code == 400

    def test_claim_second_device_rejected(self, user_client, regular_user, db):
        """User cannot claim a second device (one device per user)."""
        # User already owns a device
        Device.objects.create(
            device_id="OW:NE:D0:00:00:01",
            registration_status=RegistrationStatus.REGISTERED,
            owner=regular_user,
        )
        Device.objects.create(
            device_id="CL:AI:M0:00:00:05",
            registration_status=RegistrationStatus.UNREGISTERED,
        )
        response = user_client.post("/api/v1/devices/claim/", {
            "device_id": "CL:AI:M0:00:00:05",
        })
        assert response.status_code == 400

    def test_claim_requires_auth(self, api_client, db):
        """Unauthenticated users cannot claim devices."""
        Device.objects.create(
            device_id="CL:AI:M0:00:00:06",
            registration_status=RegistrationStatus.UNREGISTERED,
        )
        response = api_client.post("/api/v1/devices/claim/", {
            "device_id": "CL:AI:M0:00:00:06",
        })
        assert response.status_code == 401

    def test_my_devices_returns_owned(self, user_client, regular_user, db):
        """my_devices endpoint returns only devices owned by the user."""
        Device.objects.create(
            device_id="MY:DE:VI:CE:00:01",
            registration_status=RegistrationStatus.REGISTERED,
            owner=regular_user,
        )
        Device.objects.create(
            device_id="MY:DE:VI:CE:00:02",
            registration_status=RegistrationStatus.REGISTERED,
            owner=None,
        )
        response = user_client.get("/api/v1/devices/my_devices/")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["device_id"] == "MY:DE:VI:CE:00:01"
