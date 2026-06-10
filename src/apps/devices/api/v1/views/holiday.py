from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from apps.devices.api.v1.serializers.holiday import HolidaySerializer
from apps.devices.models import Device
from apps.devices.models.holiday import Holiday
from apps.devices.services.rate_limit import emergency_rate_limit
from apps.shared.permissions import IsSuperAdmin


@extend_schema_view(
    list=extend_schema(summary="List holidays", tags=["Holidays"]),
    create=extend_schema(summary="Create holiday", tags=["Holidays"]),
    partial_update=extend_schema(summary="Update holiday", tags=["Holidays"]),
    destroy=extend_schema(summary="Delete holiday", tags=["Holidays"]),
)
class HolidayViewSet(viewsets.ModelViewSet):
    """CRUD for holidays. Admin only."""

    queryset = Holiday.objects.all()
    serializer_class = HolidaySerializer
    permission_classes = [IsSuperAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["recurring"]
    search_fields = ["name"]
    ordering_fields = ["date", "created_at"]
    ordering = ["date"]

    @extend_schema(summary="Silence all devices today", tags=["Holidays"])
    @action(detail=False, methods=["post"], url_path="today-silent")
    @emergency_rate_limit(cooldown_seconds=30)
    def today_silent(self, request):
        """Send silent command to all active registered devices via Celery."""
        device_ids = list(
            Device.objects.filter(status="active", registration_status="registered").values_list("id", flat=True)
        )

        from apps.devices.tasks import broadcast_emergency_command

        broadcast_emergency_command.delay(device_ids, {"command": "silent", "state": True})

        return Response({"queued": len(device_ids)}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(summary="Cancel silence (resume bells)", tags=["Holidays"])
    @action(detail=False, methods=["post"], url_path="today-cancel")
    @emergency_rate_limit(cooldown_seconds=30)
    def today_cancel(self, request):
        """Cancel silence — resume normal bell operation via Celery."""
        device_ids = list(
            Device.objects.filter(status="active", registration_status="registered").values_list("id", flat=True)
        )

        from apps.devices.tasks import broadcast_emergency_command

        broadcast_emergency_command.delay(device_ids, {"command": "silent", "state": False})

        return Response({"queued": len(device_ids)}, status=status.HTTP_202_ACCEPTED)
