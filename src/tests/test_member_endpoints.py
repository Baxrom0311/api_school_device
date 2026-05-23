"""Tests for Member App API endpoints (/api/v1/member/)."""
import pytest
from rest_framework import status

from apps.devices.models import Device, Schedule
from apps.devices.models.device import RegistrationStatus


@pytest.fixture
def member_device(db, regular_user):
    """Device owned by regular_user with a schedule."""
    device = Device.objects.create(
        device_id="ME:MB:ER:DE:V0:01",
        school_name="Member School",
        firmware_version="1.2.0",
        owner=regular_user,
        registration_status=RegistrationStatus.REGISTERED,
        status="active",
    )
    schedule = device.schedule
    schedule.times = ["08:00", "08:45", "09:30"]
    schedule.is_active = True
    schedule.save()
    return device


@pytest.mark.django_db
class TestMyDevices:
    url = "/api/v1/member/my-devices/"

    def test_returns_user_devices(self, user_client, member_device):
        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["device_id"] == member_device.device_id

    def test_does_not_return_other_users_devices(self, user_client, admin_user, db):
        Device.objects.create(
            device_id="OT:HE:RU:SE:R0:01",
            owner=admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        device_ids = [d["device_id"] for d in resp.data["results"]]
        assert "OT:HE:RU:SE:R0:01" not in device_ids

    def test_unauthenticated_rejected(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestMySchedules:
    url = "/api/v1/member/my-schedules/"

    def test_returns_user_schedules(self, user_client, member_device):
        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["times"] == ["08:00", "08:45", "09:30"]

    def test_empty_when_no_devices(self, school_admin_client):
        resp = school_admin_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0


@pytest.mark.django_db
class TestDeviceStatus:
    url = "/api/v1/member/device-status/"

    def test_returns_lightweight_status(self, user_client, member_device):
        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        entry = resp.data[0]
        assert entry["device_id"] == member_device.device_id
        assert entry["status"] == "active"
        assert "id" in entry
        assert "last_seen" in entry

    def test_no_sensitive_fields_exposed(self, user_client, member_device):
        resp = user_client.get(self.url)
        entry = resp.data[0]
        assert "mqtt_password" not in entry
        assert "api_key" not in entry
        assert "mqtt_username" not in entry
