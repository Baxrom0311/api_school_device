"""Tests for Member App API endpoints (/api/v1/member/)."""

import pytest
from rest_framework import status

from apps.devices.models import Device
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


@pytest.mark.django_db
class TestMyBellLogs:
    url = "/api/v1/member/bell-logs/"

    def test_returns_user_bell_logs(self, user_client, member_device):
        from django.utils import timezone

        from apps.devices.models.bell_log import BellLog

        BellLog.objects.create(
            device=member_device, rang_at=timezone.now(), duration_ms=3000, trigger_source="schedule"
        )

        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1

    def test_does_not_return_other_users_bell_logs(self, user_client, admin_user, db):
        from django.utils import timezone

        from apps.devices.models.bell_log import BellLog

        other_device = Device.objects.create(device_id="OT:HE:RB:EL:L0:01", owner=admin_user)
        BellLog.objects.create(device=other_device, rang_at=timezone.now(), duration_ms=3000, trigger_source="manual")

        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0

    def test_excludes_logs_older_than_30_days(self, user_client, member_device):
        from datetime import timedelta

        from django.utils import timezone

        from apps.devices.models.bell_log import BellLog

        now = timezone.now()
        BellLog.objects.create(
            device=member_device, rang_at=now - timedelta(days=31), duration_ms=3000, trigger_source="schedule"
        )
        BellLog.objects.create(
            device=member_device, rang_at=now - timedelta(days=5), duration_ms=3000, trigger_source="manual"
        )

        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1

    def test_unauthenticated_rejected(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestMyHolidays:
    url = "/api/v1/member/holidays/"

    def test_returns_holidays(self, user_client):
        from datetime import date

        from apps.devices.models.holiday import Holiday

        Holiday.objects.create(name="Navro'z", date=date(2026, 3, 21), recurring=True)

        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["name"] == "Navro'z"

    def test_unauthenticated_rejected(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestHolidayRanges:
    url = "/api/v1/member/holiday-ranges/"

    def test_create_range(self, user_client):
        resp = user_client.post(
            self.url,
            {
                "name": "Yozgi tatil",
                "from_month": 6,
                "from_day": 1,
                "to_month": 8,
                "to_day": 31,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["name"] == "Yozgi tatil"
        assert resp.data["from_month"] == 6
        assert resp.data["to_month"] == 8

    def test_list_ranges(self, user_client):
        from apps.devices.models.holiday_range import HolidayRange

        HolidayRange.objects.create(name="Qishki tatil", from_month=12, from_day=25, to_month=1, to_day=5)

        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1

    def test_delete_range(self, user_client):
        from apps.devices.models.holiday_range import HolidayRange

        r = HolidayRange.objects.create(name="Test", from_month=1, from_day=1, to_month=1, to_day=10)

        resp = user_client.delete(f"{self.url}{r.id}/")
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert HolidayRange.objects.count() == 0

    def test_validation_invalid_month(self, user_client):
        resp = user_client.post(
            self.url,
            {
                "name": "Bad",
                "from_month": 13,
                "from_day": 1,
                "to_month": 1,
                "to_day": 1,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
