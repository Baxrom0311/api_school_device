"""Schedule Template + iCal import views."""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.devices.api.v1.serializers.schedule_template import ScheduleTemplateSerializer
from apps.devices.models import Schedule
from apps.devices.models.schedule_template import ScheduleTemplate
from apps.devices.services.ical_parser import parse_ical_to_times
from apps.shared.permissions import IsSuperAdmin

ICAL_MAX_SIZE = 1 * 1024 * 1024  # 1 MB


@extend_schema_view(
    list=extend_schema(summary="List schedule templates", tags=["Schedule Templates"]),
    create=extend_schema(summary="Create schedule template", tags=["Schedule Templates"]),
    partial_update=extend_schema(summary="Update schedule template", tags=["Schedule Templates"]),
    destroy=extend_schema(summary="Delete schedule template", tags=["Schedule Templates"]),
)
class ScheduleTemplateViewSet(viewsets.ModelViewSet):
    """CRUD for schedule templates. Admin only."""

    queryset = ScheduleTemplate.objects.all()
    serializer_class = ScheduleTemplateSerializer
    permission_classes = [IsSuperAdmin]

    @extend_schema(summary="Apply template to a device schedule", tags=["Schedule Templates"])
    @action(detail=True, methods=["post"], url_path="apply")
    def apply_to_device(self, request, pk=None):
        """Apply this template's times to a device schedule."""
        template = self.get_object()
        schedule_id = request.data.get("schedule_id")
        if not schedule_id:
            return Response({"error": "schedule_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            schedule = Schedule.objects.get(id=schedule_id)
        except Schedule.DoesNotExist:
            return Response({"error": "Schedule not found"}, status=status.HTTP_404_NOT_FOUND)

        schedule.times = template.times
        schedule.sync_pending = True
        schedule.save()
        return Response({"status": "applied", "times": template.times})

    @extend_schema(summary="Import iCal file to create/update schedule", tags=["Schedule Templates"])
    @action(detail=False, methods=["post"], url_path="import-ical", parser_classes=[MultiPartParser])
    def import_ical(self, request):
        """
        POST /api/v1/admin/schedule-templates/import-ical/
        Upload an .ics file, parse bell times, and update a schedule.
        """
        file = request.FILES.get("file")
        schedule_id = request.data.get("schedule_id")

        if not file:
            return Response({"error": "file is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not schedule_id:
            return Response({"error": "schedule_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        if file.size > ICAL_MAX_SIZE:
            return Response({"error": "File too large (max 1MB)"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            schedule = Schedule.objects.get(id=schedule_id)
        except Schedule.DoesNotExist:
            return Response({"error": "Schedule not found"}, status=status.HTTP_404_NOT_FOUND)

        content = file.read()
        times = parse_ical_to_times(content)
        if not times:
            return Response({"error": "No valid times found in iCal file"}, status=status.HTTP_400_BAD_REQUEST)

        schedule.times = times
        schedule.sync_pending = True
        schedule.save()
        return Response({"status": "imported", "times": times})

    @extend_schema(summary="Apply template to ALL device schedules", tags=["Schedule Templates"])
    @action(detail=True, methods=["post"], url_path="apply-all")
    def apply_to_all(self, request, pk=None):
        """Apply this template's times to all active device schedules."""
        template = self.get_object()
        schedules = Schedule.objects.filter(
            device__status="active",
            device__registration_status="registered",
            is_active=True,
        ).select_related("device")
        updated = 0
        for schedule in schedules:
            schedule.times = template.times
            schedule.sync_pending = True
            schedule.save()
            updated += 1
        return Response({"status": "applied", "updated_schedules": updated, "times": template.times})

    @extend_schema(summary="Import iCal from URL", tags=["Schedule Templates"])
    @action(detail=False, methods=["post"], url_path="import-ical-url")
    def import_ical_url(self, request):
        """
        POST /api/v1/admin/schedule-templates/import-ical-url/
        Fetch iCal from a URL (SSRF-safe) and update a schedule.
        """
        from apps.devices.services.url_validator import safe_fetch

        url = request.data.get("url")
        schedule_id = request.data.get("schedule_id")

        if not url or not schedule_id:
            return Response({"error": "url and schedule_id are required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            schedule = Schedule.objects.get(id=schedule_id)
        except Schedule.DoesNotExist:
            return Response({"error": "Schedule not found"}, status=status.HTTP_404_NOT_FOUND)

        content, error = safe_fetch(url, timeout=10, max_bytes=ICAL_MAX_SIZE)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        times = parse_ical_to_times(content)
        if not times:
            return Response({"error": "No valid times found in iCal"}, status=status.HTTP_400_BAD_REQUEST)

        schedule.times = times
        schedule.sync_pending = True
        schedule.save()
        return Response({"status": "imported", "times": times})
