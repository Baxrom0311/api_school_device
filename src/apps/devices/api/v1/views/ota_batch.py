"""
OTA Batch ViewSet - Manages batch OTA update operations.

WHY:
- Throttled updates (100 devices/hour) to prevent server overload
- Progress tracking for admin visibility
- Retry failed updates
- Cancel in-progress batches
"""

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from apps.devices.api.v1.serializers.ota_batch import (
    OTABatchActionSerializer,
    OTABatchCreateSerializer,
    OTABatchDeviceSerializer,
    OTABatchSerializer,
)
from apps.devices.models import OTABatch, OTABatchDevice
from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus
from apps.shared.permissions import IsSuperAdmin


@extend_schema_view(
    list=extend_schema(summary="List OTA batches", tags=["OTA Updates"]),
    retrieve=extend_schema(summary="Get OTA batch details", tags=["OTA Updates"]),
    create=extend_schema(summary="Create OTA batch", tags=["OTA Updates"]),
    destroy=extend_schema(summary="Delete OTA batch", tags=["OTA Updates"]),
)
class OTABatchViewSet(viewsets.ModelViewSet):
    """
    ViewSet for OTA batch management.

    Workflow:
    1. Create batch with firmware and device list
    2. Start batch (triggers Celery task for throttled processing)
    3. Monitor progress
    4. Retry failed devices or cancel
    """

    queryset = OTABatch.objects.select_related("firmware", "created_by").all()
    permission_classes = [IsSuperAdmin]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["status"]
    ordering_fields = ["created_at", "scheduled_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "delete"]  # No PUT/PATCH

    def get_serializer_class(self):
        if self.action == "create":
            return OTABatchCreateSerializer
        elif self.action == "batch_action":
            return OTABatchActionSerializer
        elif self.action == "devices":
            return OTABatchDeviceSerializer
        return OTABatchSerializer

    def create(self, request, *args, **kwargs):
        """Override create to return OTABatchSerializer for response."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = serializer.save()
        response_serializer = OTABatchSerializer(batch)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Perform action on batch",
        tags=["OTA Updates"],
        request=OTABatchActionSerializer,
        responses={200: OTABatchSerializer},
    )
    @action(detail=True, methods=["post"], url_path="action")
    def batch_action(self, request, pk=None):
        """
        Perform action on OTA batch.

        POST /api/v1/ota-batches/{id}/action/
        Body: {"action": "start|cancel|retry_failed"}
        """
        batch = self.get_object()
        serializer = OTABatchActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]

        if action == "start":
            return self._start_batch(batch)
        elif action == "cancel":
            return self._cancel_batch(batch)
        elif action == "retry_failed":
            return self._retry_failed(batch)

        return Response(
            {"detail": "Unknown action"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _start_batch(self, batch: OTABatch) -> Response:
        """Start OTA batch processing"""
        if batch.status != OTABatchStatus.PENDING:
            return Response(
                {"detail": f"Cannot start batch in {batch.status} status"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        batch.status = OTABatchStatus.IN_PROGRESS
        batch.started_at = timezone.now()
        batch.save(update_fields=["status", "started_at"])

        # Trigger Celery task for throttled processing
        from apps.devices.tasks import process_ota_batch

        process_ota_batch.delay(batch.id)

        serializer = OTABatchSerializer(batch)
        return Response(serializer.data)

    def _cancel_batch(self, batch: OTABatch) -> Response:
        """Cancel OTA batch"""
        if batch.status not in [OTABatchStatus.PENDING, OTABatchStatus.IN_PROGRESS]:
            return Response(
                {"detail": f"Cannot cancel batch in {batch.status} status"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        batch.status = OTABatchStatus.CANCELLED
        batch.completed_at = timezone.now()
        batch.save(update_fields=["status", "completed_at"])

        # Mark pending devices as skipped
        OTABatchDevice.objects.filter(
            batch=batch,
            status=OTADeviceStatus.PENDING,
        ).update(status=OTADeviceStatus.SKIPPED)

        serializer = OTABatchSerializer(batch)
        return Response(serializer.data)

    def _retry_failed(self, batch: OTABatch) -> Response:
        """Retry failed devices in batch"""
        if batch.status != OTABatchStatus.COMPLETED:
            return Response(
                {"detail": "Can only retry after batch completion"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        failed_count = OTABatchDevice.objects.filter(
            batch=batch,
            status=OTADeviceStatus.FAILED,
        ).update(status=OTADeviceStatus.PENDING)

        if failed_count == 0:
            return Response(
                {"detail": "No failed devices to retry"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.db.models import F

        OTABatch.objects.filter(id=batch.id).update(
            status=OTABatchStatus.IN_PROGRESS,
            failure_count=F("failure_count") - failed_count,
        )
        batch.refresh_from_db()

        # Trigger Celery task
        from apps.devices.tasks import process_ota_batch

        process_ota_batch.delay(batch.id)

        return Response(
            {
                "detail": f"Retrying {failed_count} failed devices",
                "batch": OTABatchSerializer(batch).data,
            }
        )

    @extend_schema(
        summary="Get devices in batch",
        tags=["OTA Updates"],
        responses={200: OTABatchDeviceSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def devices(self, request, pk=None):
        """
        Get list of devices in OTA batch with their status.

        GET /api/v1/ota-batches/{id}/devices/
        GET /api/v1/ota-batches/{id}/devices/?device_status=failed
        """
        batch = self.get_object()
        queryset = OTABatchDevice.objects.filter(batch=batch).select_related("device").order_by("-created_at")

        # Optional device status filter (use device_status to avoid conflict with batch status filter)
        status_filter = request.query_params.get("device_status") or request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = OTABatchDeviceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = OTABatchDeviceSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Get active batches",
        tags=["OTA Updates"],
        responses={200: OTABatchSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def active(self, request):
        """
        Get currently active OTA batches.

        GET /api/v1/ota-batches/active/
        """
        queryset = self.get_queryset().filter(status__in=[OTABatchStatus.PENDING, OTABatchStatus.IN_PROGRESS])

        serializer = OTABatchSerializer(queryset, many=True)
        return Response(serializer.data)
