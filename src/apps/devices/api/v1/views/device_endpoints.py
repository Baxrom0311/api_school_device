"""Device endpoints - called by ESP32 firmware (API key auth, no user auth)."""
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.devices.models import Device
from apps.devices.models.device import RegistrationStatus
from apps.devices.api.v1.serializers.device import (
    DeviceAutoRegisterSerializer,
    DeviceCredentialsSerializer,
)


class DeviceAutoRegisterView(APIView):
    """POST /api/v1/device/auto-register/ — ESP32 self-registration."""
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = DeviceAutoRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data["device_id"]
        firmware_version = serializer.validated_data.get("firmware_version", "0.0.0")

        device, created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={
                "firmware_version": firmware_version,
                "registration_status": RegistrationStatus.PENDING,
            },
        )

        if created:
            return Response({
                "status": "pending",
                "message": "Device registered, waiting for admin approval.",
                "device_id": device_id,
                "registration_status": "pending",
                "credentials": None,
            }, status=status.HTTP_201_CREATED)

        if device.firmware_version != firmware_version:
            device.firmware_version = firmware_version
            device.save(update_fields=["firmware_version"])

        if device.registration_status == RegistrationStatus.REGISTERED:
            return Response({
                "status": "already_registered",
                "device_id": device_id,
                "credentials": None,
                "message": "Use /device/activate/ with API key to get credentials.",
            })

        return Response({
            "status": "pending",
            "device_id": device_id,
            "registration_status": device.registration_status,
            "credentials": None,
        })


class DeviceActivateView(APIView):
    """POST /api/v1/device/activate/ — activate device with API key."""
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

        raw_password = device.regenerate_mqtt_password()
        device._raw_mqtt_password = raw_password
        return Response(DeviceCredentialsSerializer(device).data)


class DeviceCredentialsView(APIView):
    """POST /api/v1/device/credentials/ — get MQTT credentials (api_key in body)."""
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

        return Response(DeviceCredentialsSerializer(device).data)
