"""Tests for Holiday CRUD API and today-silent action."""
import pytest
from datetime import date, timedelta
from unittest.mock import patch

from django.core.cache import cache
from rest_framework import status

from apps.devices.models import Device
from apps.devices.models.holiday import Holiday


@pytest.fixture(autouse=True)
def clear_rate_limit_cache():
    """Clear rate limit cache between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestHolidayList:
    url = "/api/v1/admin/holidays/"

    def test_list_holidays(self, admin_client):
        Holiday.objects.create(name="Navro'z", date=date(2026, 3, 21), recurring=True)
        Holiday.objects.create(name="Mustaqillik", date=date(2026, 9, 1), recurring=True)

        resp = admin_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 2

    def test_filter_by_recurring(self, admin_client):
        Holiday.objects.create(name="Recurring", date=date(2026, 1, 1), recurring=True)
        Holiday.objects.create(name="One-time", date=date(2026, 6, 15), recurring=False)

        resp = admin_client.get(self.url + "?recurring=true")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["name"] == "Recurring"

    def test_search_by_name(self, admin_client):
        Holiday.objects.create(name="Navro'z", date=date(2026, 3, 21))
        Holiday.objects.create(name="Mustaqillik", date=date(2026, 9, 1))

        resp = admin_client.get(self.url + "?search=navro")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1

    def test_requires_admin(self, user_client):
        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestHolidayCreate:
    url = "/api/v1/admin/holidays/"

    def test_create_holiday(self, admin_client):
        resp = admin_client.post(self.url, {
            "name": "Navro'z",
            "date": "2026-03-21",
            "recurring": True,
        })
        assert resp.status_code == status.HTTP_201_CREATED
        assert Holiday.objects.filter(name="Navro'z").exists()

    def test_create_requires_name_and_date(self, admin_client):
        resp = admin_client.post(self.url, {"recurring": True})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_duplicate_date_name_rejected(self, admin_client):
        Holiday.objects.create(name="Test", date=date(2026, 1, 1))
        resp = admin_client.post(self.url, {"name": "Test", "date": "2026-01-01"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestHolidayUpdate:
    def test_partial_update(self, admin_client):
        h = Holiday.objects.create(name="Old Name", date=date(2026, 5, 1))
        resp = admin_client.patch(f"/api/v1/admin/holidays/{h.id}/", {"name": "New Name"})
        assert resp.status_code == status.HTTP_200_OK
        h.refresh_from_db()
        assert h.name == "New Name"


@pytest.mark.django_db
class TestHolidayDelete:
    def test_delete_holiday(self, admin_client):
        h = Holiday.objects.create(name="To Delete", date=date(2026, 12, 31))
        resp = admin_client.delete(f"/api/v1/admin/holidays/{h.id}/")
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Holiday.objects.filter(id=h.id).exists()


@pytest.mark.django_db
class TestTodaySilent:
    url = "/api/v1/admin/holidays/today-silent/"

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_silences_all_active_devices(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        resp = admin_client.post(self.url)
        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert resp.data["queued"] >= 1
        mock_task.assert_called_once()
        call_payload = mock_task.call_args[0][1]
        assert call_payload == {"command": "silent", "state": True}

    def test_requires_admin(self, user_client):
        resp = user_client.post(self.url)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_rate_limited(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        resp1 = admin_client.post(self.url)
        assert resp1.status_code == status.HTTP_202_ACCEPTED

        resp2 = admin_client.post(self.url)
        assert resp2.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
class TestTodayCancel:
    url = "/api/v1/admin/holidays/today-cancel/"

    @patch("apps.devices.tasks.broadcast_emergency_command.delay")
    def test_resumes_all_active_devices(self, mock_task, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        resp = admin_client.post(self.url)
        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert resp.data["queued"] >= 1
        call_payload = mock_task.call_args[0][1]
        assert call_payload == {"command": "silent", "state": False}

    def test_requires_admin(self, user_client):
        resp = user_client.post(self.url)
        assert resp.status_code == status.HTTP_403_FORBIDDEN
