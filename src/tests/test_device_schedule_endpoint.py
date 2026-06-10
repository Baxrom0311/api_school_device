"""Tests for device schedule HTTP endpoint (ESP32 fetches schedule)."""

import pytest

from apps.devices.models import Device, Schedule
from apps.devices.models.device import RegistrationStatus


@pytest.mark.django_db
class TestDeviceScheduleEndpoint:
    """Test GET /api/v1/device/schedule/?device_id=XXX"""

    URL = "/api/v1/device/schedule/"

    def test_returns_schedule_for_registered_device(self, api_client):
        device = Device.objects.create(
            device_id="AABBCCDDEEFF",
            school_name="Test School",
            registration_status=RegistrationStatus.REGISTERED,
        )
        Schedule.objects.filter(device=device).update(times=["08:00", "12:30", "17:00"], version=5)

        resp = api_client.get(self.URL, {"device_id": "AABBCCDDEEFF"})

        assert resp.status_code == 200
        assert resp.data["version"] == 5
        assert resp.data["times"] == ["08:00", "12:30", "17:00"]
        assert len(resp.data["entries"]) == 3
        assert resp.data["entries"][0] == {"hour": 8, "minute": 0, "duration": 3000, "days": 31}
        assert resp.data["entries"][1] == {"hour": 12, "minute": 30, "duration": 3000, "days": 31}

    def test_marks_schedule_as_synced(self, api_client):
        device = Device.objects.create(
            device_id="SYNC_HTTP_01",
            school_name="Sync School",
            registration_status=RegistrationStatus.REGISTERED,
        )
        Schedule.objects.filter(device=device).update(times=["09:00"], version=2, sync_pending=True)

        api_client.get(self.URL, {"device_id": "SYNC_HTTP_01"})

        schedule = Schedule.objects.get(device=device)
        assert schedule.sync_pending is False
        assert schedule.synced_at is not None

    def test_returns_empty_when_no_active_schedule(self, api_client):
        device = Device.objects.create(
            device_id="NO_SCHED_01",
            school_name="No Schedule",
            registration_status=RegistrationStatus.REGISTERED,
        )
        Schedule.objects.filter(device=device).update(is_active=False)

        resp = api_client.get(self.URL, {"device_id": "NO_SCHED_01"})

        assert resp.status_code == 200
        assert resp.data["version"] == 0
        assert resp.data["times"] == []

    def test_rejects_unregistered_device(self, api_client):
        Device.objects.create(
            device_id="UNREG_01",
            school_name="Unreg",
            registration_status=RegistrationStatus.PENDING,
        )

        resp = api_client.get(self.URL, {"device_id": "UNREG_01"})

        assert resp.status_code == 403

    def test_returns_404_for_unknown_device(self, api_client):
        resp = api_client.get(self.URL, {"device_id": "FFFFFFFFFFFF"})
        assert resp.status_code == 404

    def test_requires_device_id_param(self, api_client):
        resp = api_client.get(self.URL)
        assert resp.status_code == 400

    def test_normalizes_mac_with_colons(self, api_client):
        Device.objects.create(
            device_id="AABBCCDDEEFF",
            school_name="MAC Test",
            registration_status=RegistrationStatus.REGISTERED,
        )
        Schedule.objects.filter(device__device_id="AABBCCDDEEFF").update(times=["10:00"], version=1)

        resp = api_client.get(self.URL, {"device_id": "AA:BB:CC:DD:EE:FF"})

        assert resp.status_code == 200
        assert resp.data["version"] == 1
