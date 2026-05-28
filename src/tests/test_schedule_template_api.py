"""Tests for Schedule Template CRUD, apply, and iCal import endpoints."""
import pytest
from io import BytesIO
from unittest.mock import patch

from rest_framework import status

from apps.devices.models import Schedule
from apps.devices.models.schedule_template import ScheduleTemplate


@pytest.mark.django_db
class TestScheduleTemplateList:
    url = "/api/v1/admin/schedule-templates/"

    def test_list_templates(self, admin_client):
        ScheduleTemplate.objects.create(name="Standard", times=["08:00", "08:45"])
        ScheduleTemplate.objects.create(name="University", times=["09:00", "10:30"])

        resp = admin_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 2

    def test_requires_admin(self, user_client):
        resp = user_client.get(self.url)
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestScheduleTemplateCreate:
    url = "/api/v1/admin/schedule-templates/"

    def test_create_template(self, admin_client):
        resp = admin_client.post(self.url, {
            "name": "Custom",
            "times": ["07:30", "08:15", "09:00"],
            "description": "Custom schedule",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert ScheduleTemplate.objects.filter(name="Custom").exists()

    def test_create_requires_name_and_times(self, admin_client):
        resp = admin_client.post(self.url, {"description": "no name"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestScheduleTemplateApply:
    def test_apply_template_to_schedule(self, admin_client, device):
        template = ScheduleTemplate.objects.create(name="T1", times=["08:00", "12:00"])
        schedule = device.schedule

        resp = admin_client.post(
            f"/api/v1/admin/schedule-templates/{template.id}/apply/",
            {"schedule_id": str(schedule.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["times"] == ["08:00", "12:00"]

        schedule.refresh_from_db()
        assert schedule.times == ["08:00", "12:00"]
        assert schedule.sync_pending is True

    def test_apply_missing_schedule_id(self, admin_client):
        template = ScheduleTemplate.objects.create(name="T2", times=["09:00"])
        resp = admin_client.post(f"/api/v1/admin/schedule-templates/{template.id}/apply/", {})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_apply_nonexistent_schedule(self, admin_client):
        template = ScheduleTemplate.objects.create(name="T3", times=["09:00"])
        resp = admin_client.post(
            f"/api/v1/admin/schedule-templates/{template.id}/apply/",
            {"schedule_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestScheduleTemplateApplyAll:
    def test_apply_all_updates_active_schedules(self, admin_client, device):
        device.status = "active"
        device.registration_status = "registered"
        device.save()

        template = ScheduleTemplate.objects.create(name="Bulk", times=["07:00", "13:00"])

        resp = admin_client.post(f"/api/v1/admin/schedule-templates/{template.id}/apply-all/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["updated_schedules"] >= 1

        device.schedule.refresh_from_db()
        assert device.schedule.times == ["07:00", "13:00"]
        assert device.schedule.sync_pending is True

    def test_apply_all_skips_inactive_devices(self, admin_client, device):
        device.status = "inactive"
        device.save()

        template = ScheduleTemplate.objects.create(name="Bulk2", times=["10:00"])

        resp = admin_client.post(f"/api/v1/admin/schedule-templates/{template.id}/apply-all/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["updated_schedules"] == 0

    def test_apply_all_requires_admin(self, user_client):
        template = ScheduleTemplate.objects.create(name="Bulk3", times=["10:00"])
        resp = user_client.post(f"/api/v1/admin/schedule-templates/{template.id}/apply-all/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestImportIcalFile:
    url = "/api/v1/admin/schedule-templates/import-ical/"

    def test_import_ical_file(self, admin_client, device):
        ical_content = (
            b"BEGIN:VCALENDAR\r\n"
            b"BEGIN:VEVENT\r\nDTSTART:20240101T083000\r\nEND:VEVENT\r\n"
            b"BEGIN:VEVENT\r\nDTSTART:20240101T120000\r\nEND:VEVENT\r\n"
            b"END:VCALENDAR\r\n"
        )
        file = BytesIO(ical_content)
        file.name = "schedule.ics"

        schedule = device.schedule
        resp = admin_client.post(
            self.url,
            {"file": file, "schedule_id": str(schedule.id)},
            format="multipart",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "08:30" in resp.data["times"]
        assert "12:00" in resp.data["times"]

        schedule.refresh_from_db()
        assert schedule.sync_pending is True

    def test_import_no_file(self, admin_client, device):
        resp = admin_client.post(self.url, {"schedule_id": str(device.schedule.id)}, format="multipart")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_import_empty_ical(self, admin_client, device):
        file = BytesIO(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
        file.name = "empty.ics"
        resp = admin_client.post(
            self.url,
            {"file": file, "schedule_id": str(device.schedule.id)},
            format="multipart",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestImportIcalUrl:
    url = "/api/v1/admin/schedule-templates/import-ical-url/"

    @patch("apps.devices.services.url_validator.safe_fetch")
    def test_import_from_url(self, mock_fetch, admin_client, device):
        ical_content = (
            b"BEGIN:VCALENDAR\r\n"
            b"BEGIN:VEVENT\r\nDTSTART:20240101T140000\r\nEND:VEVENT\r\n"
            b"END:VCALENDAR\r\n"
        )
        mock_fetch.return_value = (ical_content, None)

        schedule = device.schedule
        resp = admin_client.post(self.url, {
            "url": "https://example.com/cal.ics",
            "schedule_id": str(schedule.id),
        })
        assert resp.status_code == status.HTTP_200_OK
        assert "14:00" in resp.data["times"]

    @patch("apps.devices.services.url_validator.safe_fetch")
    def test_blocks_redirect(self, mock_fetch, admin_client, device):
        mock_fetch.return_value = (None, "Redirects are not allowed")

        resp = admin_client.post(self.url, {
            "url": "https://evil.com/cal.ics",
            "schedule_id": str(device.schedule.id),
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Redirect" in resp.data["error"]

    def test_rejects_http_url(self, admin_client, device):
        resp = admin_client.post(self.url, {
            "url": "http://example.com/cal.ics",
            "schedule_id": str(device.schedule.id),
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "HTTPS" in resp.data["error"]

    def test_rejects_private_ip(self, admin_client, device):
        resp = admin_client.post(self.url, {
            "url": "https://192.168.1.1/cal.ics",
            "schedule_id": str(device.schedule.id),
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_params(self, admin_client):
        resp = admin_client.post(self.url, {})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
