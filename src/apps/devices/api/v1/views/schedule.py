"""
Schedule ViewSet - Handles schedule CRUD and sync operations.

WHY:
- Auto-push to device on update
- Bulk sync for pending schedules
- Validation for time format
"""
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.devices.models import Schedule
from apps.devices.api.v1.serializers.schedule import (
    ScheduleSerializer,
    ScheduleUpdateSerializer,
    ScheduleCreateSerializer,
    ScheduleBulkSyncSerializer,
)
from apps.devices.services import mqtt_publisher
from apps.shared.permissions import IsSuperAdmin, IsSchoolAdmin


@extend_schema_view(
    list=extend_schema(summary="List all schedules", tags=["Schedules"]),
    retrieve=extend_schema(summary="Get schedule details", tags=["Schedules"]),
    create=extend_schema(summary="Create schedule", tags=["Schedules"]),
    update=extend_schema(summary="Update schedule", tags=["Schedules"]),
    partial_update=extend_schema(summary="Partial update schedule", tags=["Schedules"]),
    destroy=extend_schema(summary="Delete schedule", tags=["Schedules"]),
)
class ScheduleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for schedule management.
    
    Key behavior:
    - Updating times automatically marks schedule for sync
    - Use sync_to_device action to push changes to device
    """
    queryset = Schedule.objects.select_related("device").all()
    permission_classes = [IsSchoolAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["is_active", "sync_pending"]
    search_fields = ["device__device_id", "device__school_name"]
    ordering_fields = ["created_at", "updated_at", "synced_at"]
    ordering = ["-updated_at"]
    
    def get_serializer_class(self):
        if self.action == "create":
            return ScheduleCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return ScheduleUpdateSerializer
        elif self.action == "bulk_sync":
            return ScheduleBulkSyncSerializer
        return ScheduleSerializer
    
    def get_permissions(self):
        """Admin-only for bulk operations, role-based for schedules."""
        if self.action in ["bulk_sync", "pending"]:
            return [IsSuperAdmin()]
        return [IsSchoolAdmin()]
    
    def get_queryset(self):
        """Non-admin users only see schedules for their own devices."""
        queryset = Schedule.objects.select_related("device").all()
        if (
            self.request.user.is_authenticated
            and getattr(self.request.user, "role", None) != "ADMIN"
        ):
            queryset = queryset.filter(device__owner=self.request.user)
        return queryset
    
    def perform_update(self, serializer):
        """Update schedule and optionally push to device"""
        schedule = serializer.save()
        
        # Auto-sync if requested in query params
        auto_sync = self.request.query_params.get("auto_sync", "false").lower() == "true"
        if auto_sync and schedule.sync_pending:
            self._sync_schedule(schedule)
    
    def _sync_schedule(self, schedule: Schedule) -> bool:
        """Push schedule to device via MQTT"""
        if not schedule.is_active:
            return False
        
        success = mqtt_publisher.send_schedule(
            schedule.device.device_id,
            schedule.times,
            version=schedule.version,
        )
        
        if success:
            schedule.sync_pending = False
            schedule.synced_at = timezone.now()
            schedule.save(update_fields=["sync_pending", "synced_at"])
        
        return success
    
    @extend_schema(
        summary="Sync schedule to device",
        tags=["Schedules"],
        responses={200: {"description": "Sync result"}},
    )
    @action(detail=True, methods=["post"])
    def sync_to_device(self, request, pk=None):
        """
        Push schedule to device via MQTT.
        
        POST /api/v1/schedules/{id}/sync_to_device/
        """
        schedule = self.get_object()
        
        success = self._sync_schedule(schedule)
        
        if success:
            return Response({
                "status": "success",
                "message": f"Schedule synced to {schedule.device.device_id}",
                "times_count": len(schedule.times),
            })
        else:
            return Response(
                {"status": "error", "message": "Failed to sync schedule"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
    
    @extend_schema(
        summary="Sync all pending schedules",
        tags=["Schedules"],
        request=ScheduleBulkSyncSerializer,
        responses={200: {"description": "Bulk sync results"}},
    )
    @action(detail=False, methods=["post"])
    def bulk_sync(self, request):
        """
        Sync all pending schedules to devices.
        
        POST /api/v1/schedules/bulk_sync/
        Body: {"schedule_ids": [1, 2, 3]} (optional)
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        schedule_ids = serializer.validated_data.get("schedule_ids")
        
        if schedule_ids:
            schedules = Schedule.objects.filter(
                id__in=schedule_ids,
                sync_pending=True,
            ).select_related("device")
        else:
            schedules = Schedule.objects.filter(
                sync_pending=True,
                is_active=True,
            ).select_related("device")
        
        results = {"success": 0, "failed": 0, "details": []}
        
        for schedule in schedules:
            success = self._sync_schedule(schedule)
            if success:
                results["success"] += 1
                results["details"].append({
                    "device_id": schedule.device.device_id,
                    "status": "success",
                })
            else:
                results["failed"] += 1
                results["details"].append({
                    "device_id": schedule.device.device_id,
                    "status": "failed",
                })
        
        return Response({
            "status": "completed",
            "total": results["success"] + results["failed"],
            **results,
        })
    
    @extend_schema(
        summary="Get pending schedules",
        tags=["Schedules"],
        responses={200: ScheduleSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def pending(self, request):
        """
        Get schedules that need to be synced.
        
        GET /api/v1/schedules/pending/
        """
        queryset = self.get_queryset().filter(sync_pending=True, is_active=True)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ScheduleSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = ScheduleSerializer(queryset, many=True)
        return Response(serializer.data)
