import pytest
from unittest.mock import patch

from apps.devices.models import Device, Schedule
from apps.devices.models.device import RegistrationStatus


@pytest.fixture
def device_with_schedule(db, regular_user):
    """Device with auto-created schedule (via signal) populated with times."""
    device = Device.objects.create(
        device_id="SC:HE:DU:LE:00:01",
        school_name="Schedule Test School",
        owner=regular_user,
        registration_status=RegistrationStatus.REGISTERED,
    )
    # Schedule is auto-created by signal, just update times
    schedule = device.schedule
    schedule.times = ["08:00", "08:45", "09:30", "10:15"]
    schedule.save()
    return device, schedule


@pytest.mark.django_db
class TestScheduleCRUD:
    def test_update_schedule_adds_times(self, user_client, regular_user, db):
        """New device gets empty schedule via signal; user updates it."""
        device = Device.objects.create(
            device_id="SC:HE:DU:LE:CR:01",
            owner=regular_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        schedule = device.schedule
        response = user_client.patch(f"/api/v1/schedules/{schedule.id}/", {
            "times": ["08:00", "08:45", "09:30"],
        }, format="json")
        assert response.status_code == 200
        assert response.data["times"] == ["08:00", "08:45", "09:30"]

    def test_create_schedule_duplicate_device_rejected(self, user_client, device_with_schedule):
        """Cannot create second schedule for device that already has one."""
        device, _ = device_with_schedule
        response = user_client.post("/api/v1/schedules/", {
            "device": str(device.id),
            "times": ["10:00"],
            "is_active": True,
        }, format="json")
        assert response.status_code == 400

    def test_create_schedule_other_user_device(self, user_client, admin_user, db):
        other_device = Device.objects.create(
            device_id="SC:HE:DU:LE:OT:01",
            owner=admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = user_client.post("/api/v1/schedules/", {
            "device": str(other_device.id),
            "times": ["08:00"],
            "is_active": True,
        }, format="json")
        assert response.status_code == 400

    def test_update_schedule_times(self, user_client, device_with_schedule):
        _, schedule = device_with_schedule
        response = user_client.patch(f"/api/v1/schedules/{schedule.id}/", {
            "times": ["07:30", "08:15", "09:00"],
        }, format="json")
        assert response.status_code == 200
        assert response.data["times"] == ["07:30", "08:15", "09:00"]

        schedule.refresh_from_db()
        assert schedule.sync_pending is True

    def test_update_schedule_invalid_time(self, user_client, device_with_schedule):
        _, schedule = device_with_schedule
        response = user_client.patch(f"/api/v1/schedules/{schedule.id}/", {
            "times": ["25:00", "invalid"],
        }, format="json")
        assert response.status_code == 400

    def test_list_schedules_user_sees_own(self, user_client, device_with_schedule, admin_user, db):
        admin_device = Device.objects.create(
            device_id="SC:HE:DU:LE:AD:01",
            owner=admin_user,
            registration_status=RegistrationStatus.REGISTERED,
        )
        # admin_device already has auto-created schedule via signal

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
        # device_with_schedule + admin_device + admin_user's device from conftest
        assert response.data["count"] >= 2

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_schedule", return_value=True)
    def test_sync_to_device(self, mock_send, user_client, device_with_schedule):
        _, schedule = device_with_schedule
        schedule.sync_pending = True
        schedule.save(update_fields=["sync_pending"])

        response = user_client.post(f"/api/v1/schedules/{schedule.id}/sync_to_device/")
        assert response.status_code == 200

        schedule.refresh_from_db()
        assert schedule.sync_pending is False
        assert schedule.synced_at is not None

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.send_schedule", return_value=False)
    def test_sync_to_device_failure(self, mock_send, user_client, device_with_schedule):
        _, schedule = device_with_schedule
        schedule.sync_pending = True
        schedule.save(update_fields=["sync_pending"])

        response = user_client.post(f"/api/v1/schedules/{schedule.id}/sync_to_device/")
        assert response.status_code == 503

    def test_schedule_time_validation_duplicates(self, user_client, device_with_schedule):
        _, schedule = device_with_schedule
        response = user_client.patch(f"/api/v1/schedules/{schedule.id}/", {
            "times": ["08:00", "08:00", "09:00"],
        }, format="json")
        assert response.status_code == 400

    def test_schedule_time_validation_max_entries(self, user_client, device_with_schedule):
        _, schedule = device_with_schedule
        times = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 5)][:101]
        response = user_client.patch(f"/api/v1/schedules/{schedule.id}/", {
            "times": times,
        }, format="json")
        assert response.status_code == 400
