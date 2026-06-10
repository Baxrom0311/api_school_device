from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from apps.devices.api.v1.serializers.device_log import DeviceLogSerializer
from apps.devices.models.device_log import DeviceLog
from apps.shared.permissions import IsSuperAdmin


@extend_schema_view(
    list=extend_schema(summary="List device logs", tags=["Device Logs"]),
    retrieve=extend_schema(summary="Get device log detail", tags=["Device Logs"]),
)
class DeviceLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only ViewSet for device logs. Admin only."""

    queryset = DeviceLog.objects.select_related("device").all()
    serializer_class = DeviceLogSerializer
    permission_classes = [IsSuperAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["level", "source", "device"]
    search_fields = ["message", "device__device_id", "device__school_name"]
    ordering_fields = ["created_at", "level"]
    ordering = ["-created_at"]
