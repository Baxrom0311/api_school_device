import pytest
from django.contrib.auth.hashers import make_password

from apps.devices.models import Device
from apps.devices.models.device import RegistrationStatus


@pytest.mark.django_db
class TestMQTTAuth:
    """Tests for EMQX HTTP auth plugin endpoints."""

    def test_auth_valid_credentials(self, api_client, db):
        raw_password = "mqtt_secret_123"
        device = Device.objects.create(
            device_id="MQ:TT:AU:TH:00:01",
            mqtt_username="device_MQ:TT:AU:TH:00:01",
            mqtt_password=make_password(raw_password),
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": device.mqtt_username,
            "password": raw_password,
        })
        assert response.status_code == 200
        assert response.data["result"] == "allow"

    def test_auth_invalid_password(self, api_client, db):
        Device.objects.create(
            device_id="MQ:TT:AU:TH:00:02",
            mqtt_username="device_MQ:TT:AU:TH:00:02",
            mqtt_password=make_password("correct_password"),
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": "device_MQ:TT:AU:TH:00:02",
            "password": "wrong_password",
        })
        assert response.status_code == 401

    def test_auth_unknown_username(self, api_client):
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": "nonexistent_device",
            "password": "any_password",
        })
        assert response.status_code == 401

    def test_auth_unregistered_device(self, api_client, db):
        raw_password = "mqtt_secret_456"
        Device.objects.create(
            device_id="MQ:TT:AU:TH:00:03",
            mqtt_username="device_MQ:TT:AU:TH:00:03",
            mqtt_password=make_password(raw_password),
            registration_status=RegistrationStatus.PENDING,
        )
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": "device_MQ:TT:AU:TH:00:03",
            "password": raw_password,
        })
        assert response.status_code == 403

    def test_auth_empty_credentials(self, api_client):
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": "",
            "password": "",
        })
        assert response.status_code == 400

    def test_auth_missing_fields(self, api_client):
        """Auth endpoint should reject requests with missing fields."""
        response = api_client.post("/api/v1/mqtt/auth/", {})
        assert response.status_code == 400

    def test_auth_inactive_device(self, api_client, db):
        """Device marked inactive should not authenticate."""
        raw_password = "mqtt_secret_789"
        Device.objects.create(
            device_id="MQ:TT:AU:TH:00:04",
            mqtt_username="device_MQ:TT:AU:TH:00:04",
            mqtt_password=make_password(raw_password),
            registration_status=RegistrationStatus.REGISTERED,
            status="inactive",
        )
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": "device_MQ:TT:AU:TH:00:04",
            "password": raw_password,
        })
        # Inactive devices should be denied
        assert response.status_code in [401, 403]


@pytest.mark.django_db
class TestMQTTACL:
    """Tests for EMQX HTTP ACL plugin endpoints."""

    def test_acl_own_topic_allowed(self, api_client, db):
        Device.objects.create(
            device_id="AC:L0:TE:ST:00:01",
            mqtt_username="device_ACL_01",
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/mqtt/acl/", {
            "username": "device_ACL_01",
            "topic": "devices/AC:L0:TE:ST:00:01/status",
        })
        assert response.status_code == 200
        assert response.data["result"] == "allow"

    def test_acl_other_device_topic_denied(self, api_client, db):
        Device.objects.create(
            device_id="AC:L0:TE:ST:00:02",
            mqtt_username="device_ACL_02",
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/mqtt/acl/", {
            "username": "device_ACL_02",
            "topic": "devices/OTHER_DEVICE/command",
        })
        assert response.status_code == 403

    def test_acl_unknown_device(self, api_client):
        response = api_client.post("/api/v1/mqtt/acl/", {
            "username": "unknown_device",
            "topic": "devices/something/status",
        })
        assert response.status_code == 401
