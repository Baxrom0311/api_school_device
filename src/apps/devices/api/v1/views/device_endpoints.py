"""Device endpoints - called by ESP32 firmware (API key auth, no user auth)."""

import re

from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from apps.devices.api.v1.serializers.device import (
    DeviceAutoRegisterSerializer,
)
from apps.devices.models import Device, Schedule
from apps.devices.models.device import RegistrationStatus


def _credentials_response(device):
    """Build nested credentials response matching ESP32 expected format."""
    raw_password = device.regenerate_mqtt_password()
    device._raw_mqtt_password = raw_password
    if device.mqtt_username:
        cache.delete(f"mqtt_auth:{device.mqtt_username}")
        cache.delete(f"mqtt_acl:{device.mqtt_username}")
    return Response(
        {
            "device_id": device.device_id,
            "credentials": {
                "mqtt_username": device.mqtt_username,
                "mqtt_password": raw_password,
            },
        }
    )


def _normalize_mac(mac_str):
    """Remove colons/dashes and uppercase."""
    return re.sub(r"[:\-]", "", mac_str).upper()


class DeviceAutoRegisterView(APIView):
    """POST /api/v1/device/auto-register/ — ESP32 self-registration."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "device_register"

    def post(self, request):
        serializer = DeviceAutoRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data["device_id"]
        firmware_version = serializer.validated_data.get("firmware_version", "0.0.0")
        hw_version = serializer.validated_data.get("hw_version", "1.0")

        device, created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={
                "firmware_version": firmware_version,
                "hw_version": hw_version,
                "registration_status": RegistrationStatus.PENDING,
            },
        )

        if created:
            return Response(
                {
                    "status": "pending",
                    "message": "Device registered, waiting for admin approval.",
                    "device_id": device_id,
                    "registration_status": "pending",
                    "credentials": None,
                },
                status=status.HTTP_201_CREATED,
            )

        update_fields = []
        if device.firmware_version != firmware_version:
            device.firmware_version = firmware_version
            update_fields.append("firmware_version")
        if device.hw_version != hw_version:
            device.hw_version = hw_version
            update_fields.append("hw_version")
        if update_fields:
            device.save(update_fields=update_fields)

        if device.registration_status == RegistrationStatus.REGISTERED:
            return Response(
                {
                    "status": "already_registered",
                    "device_id": device_id,
                    "api_key": device.api_key,
                    "credentials": None,
                    "message": "Use /device/activate/ with device_id to get credentials.",
                }
            )

        return Response(
            {
                "status": "pending",
                "device_id": device_id,
                "registration_status": device.registration_status,
                "credentials": None,
            }
        )


class DeviceActivateView(APIView):
    """POST /api/v1/device/activate/ — activate device by MAC or API key.

    Accepts either:
      {"device_id": "AA:BB:CC:DD:EE:FF"}  (ESP32 MAC-based activation)
      {"api_key": "sk_..."}                (admin/legacy activation)
    """

    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        device_id = request.data.get("device_id")
        api_key = request.data.get("api_key")

        if not device_id and not api_key:
            return Response(
                {"detail": "device_id or api_key is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if device_id:
            normalized = _normalize_mac(device_id)
            try:
                device = Device.objects.get(device_id=normalized)
            except Device.DoesNotExist:
                return Response(
                    {"detail": "Device not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            try:
                device = Device.objects.get(api_key=api_key)
            except Device.DoesNotExist:
                return Response(
                    {"detail": "Invalid API key"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        if device.registration_status != RegistrationStatus.REGISTERED:
            return Response(
                {"detail": "Device is not registered."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return _credentials_response(device)


class DeviceCredentialsView(APIView):
    """POST /api/v1/device/credentials/ — get MQTT credentials (api_key in body).

    Returns existing credentials if already set. Only first activation generates password.
    Use DeviceActivateView to regenerate credentials.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        api_key = request.data.get("api_key")
        if not api_key:
            return Response(
                {"detail": "api_key is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            device = Device.objects.get(api_key=api_key)
        except Device.DoesNotExist:
            return Response(
                {"detail": "Invalid API key"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if device.registration_status != RegistrationStatus.REGISTERED:
            return Response(
                {"detail": "Device is not registered."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if device.mqtt_password:
            return Response(
                {
                    "device_id": device.device_id,
                    "credentials": {
                        "mqtt_username": device.mqtt_username,
                        "mqtt_password": "***",
                    },
                    "message": "Credentials already set. Use /device/activate/ to regenerate.",
                }
            )

        return _credentials_response(device)


class DeviceScheduleView(APIView):
    """GET /api/v1/device/schedule/?device_id=XXXX — ESP32 fetches its schedule via HTTP.

    Used when device comes online and needs schedule before MQTT connects.
    Returns schedule times + version so ESP32 can compare with NVS.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        device_id = request.query_params.get("device_id")
        if not device_id:
            return Response(
                {"detail": "device_id query param is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        normalized = _normalize_mac(device_id)
        try:
            device = Device.objects.get(device_id=normalized)
        except Device.DoesNotExist:
            return Response(
                {"detail": "Device not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if device.registration_status != RegistrationStatus.REGISTERED:
            return Response(
                {"detail": "Device is not registered."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            schedule = Schedule.objects.get(device=device, is_active=True)
        except Schedule.DoesNotExist:
            return Response({"version": 0, "times": [], "entries": []})

        # Build ESP32-format entries
        entries = []
        for t in schedule.times:
            parts = t.split(":")
            if len(parts) == 2:
                entries.append(
                    {
                        "hour": int(parts[0]),
                        "minute": int(parts[1]),
                        "duration": schedule.bell_duration,
                        "days": schedule.days_mask,
                    }
                )

        # Mark as synced
        Schedule.objects.filter(pk=schedule.pk).update(sync_pending=False, synced_at=timezone.now())

        return Response(
            {
                "version": schedule.version,
                "times": schedule.times,
                "entries": entries,
            }
        )
