from unittest.mock import patch

import pytest

from apps.devices.models import Device, Schedule
from apps.devices.models.device import RegistrationStatus


@pytest.fixture
def device_with_schedule(db, school_admin_user):
    """Device with auto-created schedule (via signal) populated with times."""
    device = Device.objects.create(
        device_id="SC:HE:DU:LE:00:01",
        school_name="Schedule Test School",
        owner=school_admin_user,
        registration_status=RegistrationStatus.REGISTERED,
    )
    schedule = device.schedule
    schedule.times = ["08:00", "08:45", "09:30", "10:15"]
    schedule.save()
    return device, schedule


@pytest.mark.django_db
class TestScheduleCRUD:
    def test_update_schedule_adds_times(self, school_admin_client, school_admin_user, db):
        """New device gets empty schedule via signal; school admin updates it."""
        device = Device.objects.create(
            device_id="SC:HE:DU:LE:CR:01",
            owner=school_admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        schedule = device.schedule
        response = school_admin_client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {
                "times": ["08:00", "08:45", "09:30"],
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.data["times"] == ["08:00", "08:45", "09:30"]

    def test_create_schedule_duplicate_device_rejected(self, school_admin_client, device_with_schedule):
        """Cannot create second schedule for device that already has one."""
        device, _ = device_with_schedule
        response = school_admin_client.post(
            "/api/v1/schedules/",
            {
                "device": str(device.id),
                "times": ["10:00"],
                "is_active": True,
            },
            format="json",
        )
        assert response.status_code == 400

    def test_create_schedule_other_user_device(self, school_admin_client, admin_user, db):
        other_device = Device.objects.create(
            device_id="SC:HE:DU:LE:OT:01",
            owner=admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = school_admin_client.post(
            "/api/v1/schedules/",
            {
                "device": str(other_device.id),
                "times": ["08:00"],
                "is_active": True,
            },
            format="json",
        )
        assert response.status_code == 400

    def test_update_schedule_times(self, school_admin_client, device_with_schedule):
        _, schedule = device_with_schedule
        response = school_admin_client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {
                "times": ["07:30", "08:15", "09:00"],
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.data["times"] == ["07:30", "08:15", "09:00"]

        schedule.refresh_from_db()
        assert schedule.sync_pending is True

    def test_update_schedule_invalid_time(self, school_admin_client, device_with_schedule):
        _, schedule = device_with_schedule
        response = school_admin_client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {
                "times": ["25:00", "invalid"],
            },
            format="json",
        )
        assert response.status_code == 400

    def test_list_schedules_user_sees_own(self, user_client, regular_user, admin_user, db):
        Device.objects.create(
            device_id="SC:HE:DU:LE:US:01",
            owner=regular_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        Device.objects.create(
            device_id="SC:HE:DU:LE:AD:01",
            owner=admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )

        response = user_client.get("/api/v1/schedules/")
        assert response.status_code == 200
        assert response.data["count"] == 1

    def test_admin_sees_all_schedules(self, admin_client, device_with_schedule, admin_user, db):
        Device.objects.create(
            device_id="SC:HE:DU:LE:AD:02",
            owner=admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )

        response = admin_client.get("/api/v1/schedules/")
        assert response.status_code == 200
        assert response.data["count"] >= 2

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_schedule", return_value=True)
    def test_sync_to_device(self, mock_send, school_admin_client, device_with_schedule):
        _, schedule = device_with_schedule
        schedule.sync_pending = True
        schedule.save(update_fields=["sync_pending"])

        response = school_admin_client.post(f"/api/v1/schedules/{schedule.id}/sync_to_device/")
        assert response.status_code == 200

        schedule.refresh_from_db()
        assert schedule.sync_pending is False
        assert schedule.synced_at is not None

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_schedule", return_value=False)
    def test_sync_to_device_failure(self, mock_send, school_admin_client, device_with_schedule):
        _, schedule = device_with_schedule
        schedule.sync_pending = True
        schedule.save(update_fields=["sync_pending"])

        response = school_admin_client.post(f"/api/v1/schedules/{schedule.id}/sync_to_device/")
        assert response.status_code == 503

    def test_schedule_time_validation_duplicates(self, school_admin_client, device_with_schedule):
        _, schedule = device_with_schedule
        response = school_admin_client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {
                "times": ["08:00", "08:00", "09:00"],
            },
            format="json",
        )
        assert response.status_code == 400

    def test_schedule_time_validation_max_entries(self, school_admin_client, device_with_schedule):
        _, schedule = device_with_schedule
        times = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 5)][:101]
        response = school_admin_client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {
                "times": times,
            },
            format="json",
        )
        assert response.status_code == 400

    def test_regular_user_cannot_write_schedule(self, user_client, regular_user, db):
        """Regular USER role cannot create/update schedules."""
        device = Device.objects.create(
            device_id="SC:HE:DU:LE:RO:01",
            owner=regular_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        schedule = device.schedule
        response = user_client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {
                "times": ["08:00"],
            },
            format="json",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestScheduleVersioning:
    """Test schedule version auto-increment on times change."""

    def test_version_increments_on_times_change(self, db, school_admin_user):
        device = Device.objects.create(
            device_id="VE:RS:IO:N0:00:01",
            owner=school_admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        schedule = device.schedule
        initial_version = schedule.version

        schedule.times = ["08:00", "09:00"]
        schedule.save()
        schedule.refresh_from_db()
        assert schedule.version == initial_version + 1

        schedule.times = ["08:00", "09:00", "10:00"]
        schedule.save()
        schedule.refresh_from_db()
        assert schedule.version == initial_version + 2

    def test_version_unchanged_when_times_same(self, db, school_admin_user):
        device = Device.objects.create(
            device_id="VE:RS:IO:N0:00:02",
            owner=school_admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        schedule = device.schedule
        schedule.times = ["08:00"]
        schedule.save()
        schedule.refresh_from_db()
        v = schedule.version

        # Save again with same times — version should NOT change
        schedule.is_active = False
        schedule.save()
        schedule.refresh_from_db()
        assert schedule.version == v

    def test_sync_pending_set_on_times_change(self, db, school_admin_user):
        device = Device.objects.create(
            device_id="VE:RS:IO:N0:00:03",
            owner=school_admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        schedule = device.schedule
        schedule.sync_pending = False
        schedule.save(update_fields=["sync_pending"])

        schedule.times = ["07:30"]
        schedule.save()
        schedule.refresh_from_db()
        assert schedule.sync_pending is True


@pytest.mark.django_db
class TestScheduleAutoCreation:
    """Test that creating a device auto-creates an empty schedule via signal."""

    def test_new_device_gets_schedule(self, db, admin_user):
        device = Device.objects.create(
            device_id="AU:TO:SC:HE:D0:01",
            owner=admin_user,
        )
        assert hasattr(device, "schedule")
        assert device.schedule.times == []
        assert device.schedule.is_active is True

    def test_schedule_not_duplicated_on_device_save(self, db, admin_user):
        device = Device.objects.create(
            device_id="AU:TO:SC:HE:D0:02",
            owner=admin_user,
        )
        device.school_name = "Updated"
        device.save()
        assert Schedule.objects.filter(device=device).count() == 1
