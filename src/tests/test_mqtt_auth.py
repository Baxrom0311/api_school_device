import pytest
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from unittest.mock import patch

from apps.devices.models import Device
from apps.devices.models.device import RegistrationStatus

MOCK_SECRET = "test_mqtt_secret"


@pytest.mark.django_db
class TestMQTTAuth:
    """Tests for EMQX HTTP auth plugin endpoints."""

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
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
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 200
        assert response.data["result"] == "allow"

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
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
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 401

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_auth_unknown_username(self, api_client):
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": "nonexistent_device",
            "password": "any_password",
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 401

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
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
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 403

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_auth_empty_credentials(self, api_client):
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": "",
            "password": "",
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 400

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_auth_missing_fields(self, api_client):
        """Auth endpoint should reject requests with missing fields."""
        response = api_client.post("/api/v1/mqtt/auth/", {},
                                   HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 400

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
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
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        # Inactive devices should be denied
        assert response.status_code in [401, 403]

    def test_auth_no_secret_configured(self, api_client):
        """When MQTT_AUTH_SECRET is empty, all requests should be denied (fail-closed)."""
        response = api_client.post("/api/v1/mqtt/auth/", {
            "username": "any",
            "password": "any",
        })
        assert response.status_code == 403

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_auth_caching_avoids_db_hit(self, api_client, db):
        """Second auth call should use cache and not hit the database."""
        raw_password = "mqtt_cache_test"
        Device.objects.create(
            device_id="MQ:TT:CA:CH:00:01",
            mqtt_username="device_cache_01",
            mqtt_password=make_password(raw_password),
            registration_status=RegistrationStatus.REGISTERED,
        )
        cache.clear()

        # First call — populates cache
        resp1 = api_client.post("/api/v1/mqtt/auth/", {
            "username": "device_cache_01",
            "password": raw_password,
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert resp1.status_code == 200

        # Delete device from DB — second call should still succeed via cache
        Device.objects.filter(mqtt_username="device_cache_01").delete()

        resp2 = api_client.post("/api/v1/mqtt/auth/", {
            "username": "device_cache_01",
            "password": raw_password,
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert resp2.status_code == 200


@pytest.mark.django_db
class TestMQTTACL:
    """Tests for EMQX HTTP ACL plugin endpoints."""

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_acl_own_topic_allowed(self, api_client, db):
        Device.objects.create(
            device_id="AC:L0:TE:ST:00:01",
            mqtt_username="device_ACL_01",
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/mqtt/acl/", {
            "username": "device_ACL_01",
            "topic": "devices/AC:L0:TE:ST:00:01/status",
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 200
        assert response.data["result"] == "allow"

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_acl_other_device_topic_denied(self, api_client, db):
        Device.objects.create(
            device_id="AC:L0:TE:ST:00:02",
            mqtt_username="device_ACL_02",
            registration_status=RegistrationStatus.REGISTERED,
        )
        response = api_client.post("/api/v1/mqtt/acl/", {
            "username": "device_ACL_02",
            "topic": "devices/OTHER_DEVICE/command",
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 403

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_acl_unknown_device(self, api_client):
        response = api_client.post("/api/v1/mqtt/acl/", {
            "username": "unknown_device",
            "topic": "devices/something/status",
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert response.status_code == 401


@pytest.mark.django_db
class TestMQTTCacheInvalidation:
    """Tests for MQTT cache invalidation on device status change."""

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_deactivating_device_invalidates_mqtt_cache(self, api_client, db):
        """When a device is deactivated, its cached MQTT auth should be cleared."""
        raw_password = "mqtt_pass_cache"
        device = Device.objects.create(
            device_id="CA:CH:EI:NV:00:01",
            mqtt_username="device_cache_inv",
            mqtt_password=make_password(raw_password),
            registration_status=RegistrationStatus.REGISTERED,
            status="active",
        )

        # First auth populates cache
        api_client.post("/api/v1/mqtt/auth/", {
            "username": device.mqtt_username,
            "password": raw_password,
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert cache.get(f"mqtt_auth:{device.mqtt_username}") is not None

        # Deactivate device — signal should clear cache
        device.status = "inactive"
        device.save(update_fields=["status"])

        assert cache.get(f"mqtt_auth:{device.mqtt_username}") is None
        assert cache.get(f"mqtt_acl:{device.mqtt_username}") is None

    @patch("apps.devices.api.v1.views.mqtt_auth.MQTT_AUTH_SECRET", MOCK_SECRET)
    def test_unregistering_device_invalidates_mqtt_cache(self, api_client, db):
        """When registration_status changes, cached MQTT auth should be cleared."""
        raw_password = "mqtt_pass_unreg"
        device = Device.objects.create(
            device_id="CA:CH:EI:NV:00:02",
            mqtt_username="device_cache_unreg",
            mqtt_password=make_password(raw_password),
            registration_status=RegistrationStatus.REGISTERED,
            status="active",
        )

        # Populate cache
        api_client.post("/api/v1/mqtt/auth/", {
            "username": device.mqtt_username,
            "password": raw_password,
        }, HTTP_X_MQTT_AUTH_SECRET=MOCK_SECRET)
        assert cache.get(f"mqtt_auth:{device.mqtt_username}") is not None

        # Unregister device
        device.registration_status = RegistrationStatus.UNREGISTERED
        device.save(update_fields=["registration_status"])

        assert cache.get(f"mqtt_auth:{device.mqtt_username}") is None
