from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend, FilterSet, DateTimeFilter
from drf_spectacular.utils import extend_schema_view, extend_schema

from apps.devices.models.bell_log import BellLog
from apps.devices.api.v1.serializers.bell_log import BellLogSerializer
from apps.shared.permissions import IsSuperAdmin


class BellLogFilter(FilterSet):
    rang_at__gte = DateTimeFilter(field_name="rang_at", lookup_expr="gte")
    rang_at__lte = DateTimeFilter(field_name="rang_at", lookup_expr="lte")

    class Meta:
        model = BellLog
        fields = ["device", "trigger_source"]


@extend_schema_view(
    list=extend_schema(summary="List bell logs", tags=["Bell Logs"]),
    retrieve=extend_schema(summary="Get bell log detail", tags=["Bell Logs"]),
)
class BellLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only bell log history with date range filtering. Admin only."""

    serializer_class = BellLogSerializer
    permission_classes = [IsSuperAdmin]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = BellLogFilter
    ordering_fields = ["rang_at", "created_at"]
    ordering = ["-rang_at"]

    def get_queryset(self):
        return BellLog.objects.select_related("device")
