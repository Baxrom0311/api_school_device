import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(
        email="admin@test.com",
        password="testpass123",
        username="admin",
        role="ADMIN",
        is_verified=True,
    )
    return user


@pytest.fixture
def regular_user(db):
    user = User.objects.create_user(
        email="user@test.com",
        password="testpass123",
        username="regular",
        role="USER",
        is_verified=True,
    )
    return user


@pytest.fixture
def unverified_user(db):
    user = User.objects.create_user(
        email="unverified@test.com",
        password="testpass123",
        username="unverified",
        role="USER",
        is_verified=False,
    )
    return user


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def user_client(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)
    return api_client


@pytest.fixture
def device(db, admin_user):
    from apps.devices.models import Device

    return Device.objects.create(
        device_id="AA:BB:CC:DD:EE:FF",
        school_name="Test School",
        firmware_version="1.0.0",
        owner=admin_user,
    )


@pytest.fixture
def user_device(db, regular_user):
    from apps.devices.models import Device
    from apps.devices.models.device import RegistrationStatus

    return Device.objects.create(
        device_id="11:22:33:44:55:66",
        school_name="User School",
        firmware_version="1.0.0",
        owner=regular_user,
        registration_status=RegistrationStatus.REGISTERED,
    )
