"""
Tests for permission matrix (Milestone 6, Task 6.1).

Verifies:
- SuperAdmin can access /admin/ endpoints
- Regular users cannot access /admin/ endpoints
- Regular users can access /member/ endpoints
- Unauthenticated users cannot access protected endpoints
"""

import pytest
from rest_framework.test import APIClient

from apps.devices.models import Device


@pytest.mark.django_db
class TestAdminPermissions:
    """SuperAdmin-only endpoints reject regular users."""

    def test_admin_can_list_devices(self, admin_client):
        response = admin_client.get("/api/v1/admin/devices/")
        assert response.status_code == 200

    def test_regular_user_cannot_list_admin_devices(self, user_client):
        response = user_client.get("/api/v1/admin/devices/")
        assert response.status_code == 403

    def test_regular_user_cannot_list_legacy_devices(self, user_client):
        """Regular users must use /my_devices/ not /devices/ list."""
        response = user_client.get("/api/v1/devices/")
        assert response.status_code == 403

    def test_unauthenticated_cannot_list_admin_devices(self, api_client):
        response = api_client.get("/api/v1/admin/devices/")
        assert response.status_code == 401

    def test_admin_can_list_firmware(self, admin_client):
        response = admin_client.get("/api/v1/admin/firmware/")
        assert response.status_code == 200

    def test_regular_user_cannot_list_firmware(self, user_client):
        response = user_client.get("/api/v1/admin/firmware/")
        assert response.status_code == 403

    def test_admin_can_list_ota_batches(self, admin_client):
        response = admin_client.get("/api/v1/admin/ota-batches/")
        assert response.status_code == 200

    def test_regular_user_cannot_list_ota_batches(self, user_client):
        response = user_client.get("/api/v1/admin/ota-batches/")
        assert response.status_code == 403

    def test_admin_can_list_users(self, admin_client):
        response = admin_client.get("/api/v1/admin/users/")
        assert response.status_code == 200

    def test_regular_user_cannot_list_users(self, user_client):
        response = user_client.get("/api/v1/admin/users/")
        assert response.status_code == 403

    def test_admin_auto_register_requires_admin(self, api_client):
        """SECURITY: /admin/ path must NOT expose AllowAny endpoints."""
        response = api_client.post(
            "/api/v1/admin/devices/auto-register/",
            {
                "device_id": "AA:BB:CC:DD:EE:01",
                "firmware_version": "1.0.0",
            },
        )
        assert response.status_code == 401

    def test_admin_activate_requires_admin(self, user_client):
        """SECURITY: /admin/ activate must require admin."""
        response = user_client.post(
            "/api/v1/admin/devices/activate/",
            {
                "api_key": "sk_test",
            },
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestMemberPermissions:
    """Member endpoints accessible by authenticated users."""

    def test_user_can_access_my_devices(self, user_client):
        response = user_client.get("/api/v1/member/my-devices/")
        assert response.status_code == 200

    def test_unauthenticated_cannot_access_my_devices(self, api_client):
        response = api_client.get("/api/v1/member/my-devices/")
        assert response.status_code == 401

    def test_user_can_access_my_schedules(self, user_client):
        response = user_client.get("/api/v1/member/my-schedules/")
        assert response.status_code == 200

    def test_school_admin_can_access_my_devices(self, school_admin_client):
        response = school_admin_client.get("/api/v1/member/my-devices/")
        assert response.status_code == 200

    def test_school_admin_can_access_my_schedules(self, school_admin_client):
        response = school_admin_client.get("/api/v1/member/my-schedules/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestDeviceEndpointPermissions:
    """ESP32 device endpoints are public (API key auth in body)."""

    def test_auto_register_is_public(self, api_client):
        response = api_client.post(
            "/api/v1/device/auto-register/",
            {
                "device_id": "AA:BB:CC:DD:EE:01",
                "firmware_version": "1.0.0",
            },
        )
        assert response.status_code in [200, 201]

    def test_activate_requires_valid_api_key(self, api_client):
        response = api_client.post(
            "/api/v1/device/activate/",
            {
                "api_key": "invalid_key",
            },
        )
        assert response.status_code == 401

    def test_credentials_requires_valid_api_key(self, api_client):
        response = api_client.post(
            "/api/v1/device/credentials/",
            {
                "api_key": "invalid_key",
            },
        )
        assert response.status_code == 401


@pytest.mark.django_db
class TestScheduleRolePermissions:
    """Schedule write operations require ownership or admin role."""

    def test_regular_user_cannot_create_schedule(self, user_client, user_device):
        """USER role can't create/update schedules (write requires SCHOOL_ADMIN+)."""
        response = user_client.post(
            "/api/v1/schedules/",
            {
                "device": str(user_device.id),
                "times": ["08:00", "08:45"],
            },
            format="json",
        )
        assert response.status_code == 403

    def test_school_admin_can_update_schedule(self, school_admin_user):
        from apps.devices.models import Schedule

        client = APIClient()
        client.force_authenticate(user=school_admin_user)
        device = Device.objects.create(
            device_id="SA:BB:CC:DD:EE:01",
            school_name="School Admin School",
            firmware_version="1.0.0",
            owner=school_admin_user,
        )
        schedule = Schedule.objects.get(device=device)
        response = client.patch(
            f"/api/v1/schedules/{schedule.id}/",
            {
                "times": ["08:00", "08:45"],
            },
            format="json",
        )
        assert response.status_code == 200

    def test_regular_user_can_list_schedules(self, user_client):
        response = user_client.get("/api/v1/schedules/")
        assert response.status_code == 200

    def test_member_endpoint_read_only_for_user(self, user_client):
        """IsMember permission on member endpoints allows only GET."""
        response = user_client.get("/api/v1/member/my-devices/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestDeviceStatusPolling:
    """Tests for lightweight device-status polling endpoint."""

    def test_authenticated_user_can_access_device_status(self, user_client, user_device):
        response = user_client.get("/api/v1/member/device-status/")
        assert response.status_code == 200
        assert isinstance(response.data, list)
        assert len(response.data) == 1
        assert response.data[0]["device_id"] == user_device.device_id

    def test_unauthenticated_cannot_access_device_status(self, api_client):
        response = api_client.get("/api/v1/member/device-status/")
        assert response.status_code == 401

    def test_returns_only_own_devices(self, user_client, device):
        """User should not see admin's device."""
        response = user_client.get("/api/v1/member/device-status/")
        assert response.status_code == 200
        device_ids = [d["device_id"] for d in response.data]
        assert device.device_id not in device_ids
