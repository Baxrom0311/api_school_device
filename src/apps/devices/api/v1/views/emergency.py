from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.api.v1.serializers.emergency import DeviceAlertSerializer
from apps.devices.models import Device
from apps.devices.models.device_alert import DeviceAlert
from apps.devices.services.rate_limit import emergency_rate_limit
from apps.shared.permissions import IsSuperAdmin


class EmergencyAlertListView(ListAPIView):
    """List all emergency alerts (paginated, filterable)."""

    serializer_class = DeviceAlertSerializer
    permission_classes = [IsSuperAdmin]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["alert_type", "resolved", "device"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return DeviceAlert.objects.select_related("device").all()


class EmergencyRingAllView(APIView):
    """Send emergency ring (30s) to all active devices via Celery."""

    permission_classes = [IsSuperAdmin]

    @extend_schema(summary="Emergency ring all devices", tags=["Emergency"])
    @emergency_rate_limit(cooldown_seconds=30)
    def post(self, request):
        try:
            duration = min(int(request.data.get("duration", 30)), 60)
        except (TypeError, ValueError):
            return Response({"error": "duration must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        if duration < 1:
            return Response({"error": "duration must be between 1 and 60"}, status=status.HTTP_400_BAD_REQUEST)

        device_ids = list(
            Device.objects.filter(status="active", registration_status="registered").values_list("id", flat=True)
        )

        DeviceAlert.objects.create(alert_type=DeviceAlert.AlertType.EMERGENCY_RING)

        if device_ids:
            from apps.devices.tasks import broadcast_emergency_command

            broadcast_emergency_command.delay(device_ids, {"command": "ring", "duration": duration})

        return Response({"queued": len(device_ids)}, status=status.HTTP_202_ACCEPTED)


class EmergencyLockdownView(APIView):
    """Send lockdown command (relay 2) to all active devices via Celery."""

    permission_classes = [IsSuperAdmin]

    @extend_schema(summary="Lockdown all devices", tags=["Emergency"])
    @emergency_rate_limit(cooldown_seconds=30)
    def post(self, request):
        raw_state = request.data.get("state", True)
        if isinstance(raw_state, str):
            state = raw_state.lower() not in ("false", "0", "")
        else:
            state = bool(raw_state)

        device_ids = list(
            Device.objects.filter(status="active", registration_status="registered").values_list("id", flat=True)
        )

        DeviceAlert.objects.create(alert_type=DeviceAlert.AlertType.LOCKDOWN)

        if device_ids:
            from apps.devices.tasks import broadcast_emergency_command

            broadcast_emergency_command.delay(device_ids, {"command": "lockdown", "state": state})

        return Response({"queued": len(device_ids)}, status=status.HTTP_202_ACCEPTED)


class EmergencyCancelView(APIView):
    """Resolve all active alerts and send cancel to devices via Celery."""

    permission_classes = [IsSuperAdmin]

    @extend_schema(summary="Cancel emergency / resolve alerts", tags=["Emergency"])
    @emergency_rate_limit(cooldown_seconds=30)
    def post(self, request):
        now = timezone.now()
        resolved = DeviceAlert.objects.filter(resolved=False).update(resolved=True, resolved_at=now)

        device_ids = list(
            Device.objects.filter(status="active", registration_status="registered").values_list("id", flat=True)
        )

        if device_ids:
            from apps.devices.tasks import broadcast_emergency_command

            broadcast_emergency_command.delay(device_ids, {"command": "cancel_emergency"})

        return Response({"resolved_alerts": resolved}, status=status.HTTP_200_OK)
