"""Tests for ESP32 device endpoints (auto-register, activate, credentials)."""
import pytest
from django.contrib.auth.hashers import check_password
from rest_framework import status

from apps.devices.models import Device
from apps.devices.models.device import RegistrationStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def registered_device():
    """A device that has been approved by admin (registered status)."""
    device = Device.objects.create(
        device_id="DEADBEEF0001",
        school_name="Test School",
        firmware_version="1.0.0",
        registration_status=RegistrationStatus.REGISTERED,
    )
    return device


@pytest.fixture
def pending_device():
    """A device still waiting for admin approval."""
    device = Device.objects.create(
        device_id="DEADBEEF0002",
        school_name="",
        firmware_version="1.0.0",
        registration_status=RegistrationStatus.PENDING,
    )
    return device


class TestDeviceAutoRegister:
    url = "/api/v1/device/auto-register/"

    def test_new_device_registers_as_pending(self, api_client):
        resp = api_client.post(self.url, {"device_id": "AA:BB:CC:DD:EE:01", "firmware_version": "1.0.0"})
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["status"] == "pending"
        assert Device.objects.filter(device_id="AABBCCDDEE01").exists()

    def test_existing_registered_device_returns_already_registered(self, api_client, registered_device):
        resp = api_client.post(self.url, {"device_id": "DE:AD:BE:EF:00:01", "firmware_version": "1.0.0"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["status"] == "already_registered"
        assert resp.data["api_key"] == registered_device.api_key

    def test_existing_pending_device_returns_pending(self, api_client, pending_device):
        resp = api_client.post(self.url, {"device_id": "DE:AD:BE:EF:00:02", "firmware_version": "1.0.0"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["registration_status"] == "pending"

    def test_updates_firmware_version_for_registered(self, api_client, registered_device):
        api_client.post(self.url, {"device_id": "DE:AD:BE:EF:00:01", "firmware_version": "2.0.0"})
        registered_device.refresh_from_db()
        assert registered_device.firmware_version == "2.0.0"

    def test_missing_device_id_returns_400(self, api_client):
        resp = api_client.post(self.url, {"firmware_version": "1.0.0"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_mac_format_returns_400(self, api_client):
        resp = api_client.post(self.url, {"device_id": "not-a-mac", "firmware_version": "1.0.0"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestDeviceActivate:
    url = "/api/v1/device/activate/"

    def test_activate_with_valid_api_key(self, api_client, registered_device):
        resp = api_client.post(self.url, {"api_key": registered_device.api_key})
        assert resp.status_code == status.HTTP_200_OK
        assert "credentials" in resp.data
        assert "mqtt_username" in resp.data["credentials"]
        assert "mqtt_password" in resp.data["credentials"]

    def test_activate_with_device_id_mac(self, api_client, registered_device):
        """ESP32 sends MAC address as device_id for activation."""
        mac = "DE:AD:BE:EF:00:01"
        resp = api_client.post(self.url, {"device_id": mac})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["device_id"] == "DEADBEEF0001"
        assert "credentials" in resp.data
        assert resp.data["credentials"]["mqtt_username"] is not None
        assert resp.data["credentials"]["mqtt_password"] != "***"

    def test_activate_pending_device_by_mac_returns_403(self, api_client, pending_device):
        resp = api_client.post(self.url, {"device_id": "DE:AD:BE:EF:00:02"})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_activate_pending_device_returns_403(self, api_client, pending_device):
        resp = api_client.post(self.url, {"api_key": pending_device.api_key})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_invalid_api_key_returns_401(self, api_client):
        resp = api_client.post(self.url, {"api_key": "sk_invalid_key_12345"})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unknown_mac_returns_404(self, api_client):
        resp = api_client.post(self.url, {"device_id": "FF:FF:FF:FF:FF:FF"})
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_missing_both_fields_returns_400(self, api_client):
        resp = api_client.post(self.url, {})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_regenerates_mqtt_password(self, api_client, registered_device):
        resp = api_client.post(self.url, {"api_key": registered_device.api_key})
        raw_password = resp.data["credentials"]["mqtt_password"]
        registered_device.refresh_from_db()
        assert check_password(raw_password, registered_device.mqtt_password)

    def test_full_esp32_flow(self, api_client):
        """Integration: auto-register → admin approves → activate by MAC → get credentials."""
        # Step 1: ESP32 auto-registers
        resp = api_client.post("/api/v1/device/auto-register/", {
            "device_id": "AA:BB:CC:DD:EE:FF",
            "firmware_version": "1.0.0",
        })
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["status"] == "pending"

        # Step 2: Admin approves (simulate)
        device = Device.objects.get(device_id="AABBCCDDEEFF")
        device.registration_status = RegistrationStatus.REGISTERED
        device.school_name = "Test School"
        device.save()

        # Step 3: ESP32 activates by MAC
        resp = api_client.post(self.url, {"device_id": "AA:BB:CC:DD:EE:FF"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["device_id"] == "AABBCCDDEEFF"
        assert resp.data["credentials"]["mqtt_username"] is not None
        assert len(resp.data["credentials"]["mqtt_password"]) > 0


class TestDeviceCredentials:
    url = "/api/v1/device/credentials/"

    def test_get_credentials_registered_device(self, api_client, registered_device):
        resp = api_client.post(self.url, {"api_key": registered_device.api_key})
        assert resp.status_code == status.HTTP_200_OK
        assert "credentials" in resp.data
        assert "mqtt_username" in resp.data["credentials"]

    def test_pending_device_returns_403(self, api_client, pending_device):
        resp = api_client.post(self.url, {"api_key": pending_device.api_key})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_invalid_api_key_returns_401(self, api_client):
        resp = api_client.post(self.url, {"api_key": "sk_bogus"})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_missing_api_key_returns_400(self, api_client):
        resp = api_client.post(self.url, {})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
