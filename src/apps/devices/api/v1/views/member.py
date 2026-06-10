"""Member views - endpoints for SchoolAdmin and Member roles."""

from datetime import timedelta

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.api.v1.serializers.bell_log import BellLogSerializer
from apps.devices.api.v1.serializers.device import DeviceListSerializer
from apps.devices.api.v1.serializers.emergency import DeviceAlertSerializer
from apps.devices.api.v1.serializers.holiday import HolidaySerializer
from apps.devices.api.v1.serializers.schedule import ScheduleHistorySerializer, ScheduleSerializer
from apps.devices.models import Device, Schedule, ScheduleHistory
from apps.devices.models.bell_log import BellLog
from apps.devices.models.device_alert import DeviceAlert
from apps.devices.models.holiday import Holiday
from apps.devices.services import mqtt_publisher
from apps.shared.permissions import IsMember


class MyDevicesView(generics.ListAPIView):
    """GET /api/v1/member/my-devices/ — devices owned by current user."""

    serializer_class = DeviceListSerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        return Device.objects.filter(owner=self.request.user).select_related("schedule").order_by("-created_at")


class MySchedulesView(generics.ListAPIView):
    """GET /api/v1/member/my-schedules/ — schedules for current user's devices."""

    serializer_class = ScheduleSerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        return Schedule.objects.filter(device__owner=self.request.user).select_related("device").order_by("-updated_at")


class MyScheduleHistoryView(generics.ListAPIView):
    """GET /api/v1/member/schedule-history/<device_id>/ — previous schedule versions."""

    serializer_class = ScheduleHistorySerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        device_id = self.kwargs["device_id"]
        return ScheduleHistory.objects.filter(
            device_id=device_id,
            device__owner=self.request.user,
        ).order_by("-created_at")[:50]


class MyDeviceStatusView(APIView):
    """GET /api/v1/member/device-status/ — lightweight polling endpoint for device status.

    Returns minimal data for real-time status updates without full serialization overhead.
    Includes schedule_stale flag for dashboard badge.
    """

    permission_classes = [IsMember]

    def get(self, request):
        devices = Device.objects.filter(owner=request.user).values(
            "id",
            "device_id",
            "status",
            "last_seen",
            "rtc_synced",
            "rtc_battery_status",
            "rtc_consecutive_drift_days",
        )
        result = []
        stale_threshold = timezone.now() - timedelta(days=7)
        for d in devices:
            d["schedule_stale"] = False
            d["rtc_battery_dead"] = d.get("rtc_battery_status") == "dead"
            try:
                schedule = Schedule.objects.only("synced_at", "created_at").get(device_id=d["id"])
                synced = schedule.synced_at or schedule.created_at
                if synced < stale_threshold:
                    d["schedule_stale"] = True
            except Schedule.DoesNotExist:
                pass
            result.append(d)
        return Response(result)


class MyHolidaysView(generics.ListAPIView):
    """GET /api/v1/member/holidays/ — read-only holiday list with optional date filter."""

    serializer_class = HolidaySerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        queryset = Holiday.objects.all()
        date = self.request.query_params.get("date")
        if date:
            queryset = queryset.filter(date=date)
        return queryset


class MemberHolidayCreateView(generics.CreateAPIView):
    """POST /api/v1/member/holidays/create/ — create a holiday."""

    serializer_class = HolidaySerializer
    permission_classes = [IsMember]

    def perform_create(self, serializer):
        serializer.save()
        from apps.devices.tasks import sync_holidays_to_devices

        sync_holidays_to_devices.delay()


class MemberHolidayDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/member/holidays/<id>/ — delete a holiday."""

    serializer_class = HolidaySerializer
    permission_classes = [IsMember]
    queryset = Holiday.objects.all()

    def perform_destroy(self, instance):
        instance.delete()
        from apps.devices.tasks import sync_holidays_to_devices

        sync_holidays_to_devices.delay()


class MemberTodaySilentView(APIView):
    """POST /api/v1/member/holidays/today-silent/ — silence all devices today."""

    permission_classes = [IsMember]

    def post(self, request):
        device_ids = list(Device.objects.filter(owner=request.user, status="active").values_list("id", flat=True))
        if not device_ids:
            return Response({"detail": "No active devices"}, status=status.HTTP_404_NOT_FOUND)

        from apps.devices.tasks import broadcast_emergency_command

        broadcast_emergency_command.delay(device_ids, {"command": "silent", "state": True})
        return Response({"queued": len(device_ids)}, status=status.HTTP_202_ACCEPTED)


class MyBellLogsView(generics.ListAPIView):
    """GET /api/v1/member/bell-logs/ — bell logs for current user's devices."""

    serializer_class = BellLogSerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        return (
            BellLog.objects.filter(
                device__owner=self.request.user,
                rang_at__gte=timezone.now() - timedelta(days=30),
            )
            .select_related("device")
            .order_by("-rang_at")
        )


class MyAlertsView(generics.ListAPIView):
    """GET /api/v1/member/alerts/ — unresolved alerts for current user's devices.

    Dashboard uses this to show badges like "RTC ⚠️ Batareya zaiflashgan".
    """

    serializer_class = DeviceAlertSerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        return (
            DeviceAlert.objects.filter(
                device__owner=self.request.user,
                resolved=False,
            )
            .select_related("device")
            .order_by("-created_at")
        )


class MemberAlertResolveView(APIView):
    """POST /api/v1/member/alerts/<id>/resolve/ — resolve an alert."""

    permission_classes = [IsMember]

    def post(self, request, pk=None):
        try:
            alert = DeviceAlert.objects.get(pk=pk, device__owner=request.user)
        except DeviceAlert.DoesNotExist:
            return Response({"detail": "Alert not found"}, status=status.HTTP_404_NOT_FOUND)
        alert.resolved = True
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["resolved", "resolved_at"])
        return Response({"status": "resolved"})


class MemberDeviceRingView(APIView):
    """POST /api/v1/member/devices/<device_id>/ring/ — ring own device."""

    permission_classes = [IsMember]

    def post(self, request, device_id=None):
        try:
            device = Device.objects.get(pk=device_id, owner=request.user)
        except Device.DoesNotExist:
            return Response({"detail": "Device not found"}, status=status.HTTP_404_NOT_FOUND)

        duration = request.data.get("duration", 5)
        try:
            duration = min(int(duration), 30)
        except (TypeError, ValueError):
            duration = 5

        msg_id = mqtt_publisher.ring(device.device_id, duration)
        if msg_id:
            return Response({"status": "success", "duration": duration, "msg_id": msg_id})
        return Response(
            {"status": "error", "message": "Failed to send ring command"}, status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


class MemberDeviceEmergencyView(APIView):
    """POST /api/v1/member/devices/<device_id>/emergency/ — trigger emergency on own device."""

    permission_classes = [IsMember]

    def post(self, request, device_id=None):
        try:
            device = Device.objects.get(pk=device_id, owner=request.user)
        except Device.DoesNotExist:
            return Response({"detail": "Device not found"}, status=status.HTTP_404_NOT_FOUND)

        alert_type = request.data.get("alert_type", "panic")
        if alert_type not in ("panic", "lockdown", "emergency_ring"):
            return Response({"detail": "Invalid alert_type"}, status=status.HTTP_400_BAD_REQUEST)

        DeviceAlert.objects.create(device=device, alert_type=alert_type)

        command_map = {
            "panic": {"command": "ring", "duration": 30},
            "emergency_ring": {"command": "ring", "duration": 30},
            "lockdown": {"command": "lockdown", "state": True},
        }
        mqtt_publisher.send_to_device(device.device_id, command_map[alert_type], qos=1)
        return Response({"status": "success", "alert_type": alert_type})


class CommandStatusView(APIView):
    """GET /api/v1/member/commands/<msg_id>/status/ — get command delivery status."""

    permission_classes = [IsMember]

    def get(self, request, msg_id=None):
        from apps.devices.models.command_log import CommandLog

        try:
            cmd = CommandLog.objects.get(msg_id=msg_id, device__owner=request.user)
        except CommandLog.DoesNotExist:
            return Response({"detail": "Command not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "msg_id": str(cmd.msg_id),
                "status": cmd.status,
                "command_type": cmd.command_type,
                "sent_at": cmd.sent_at,
                "acked_at": cmd.acked_at,
                "error_message": cmd.error_message,
            }
        )


class RecentCommandsView(APIView):
    """GET /api/v1/member/commands/recent/ — last 10 commands for user's devices."""

    permission_classes = [IsMember]

    def get(self, request):
        from apps.devices.models.command_log import CommandLog

        cmds = CommandLog.objects.filter(device__owner=request.user).order_by("-sent_at")[:10]
        data = [
            {
                "msg_id": str(c.msg_id),
                "device_id": c.device.device_id,
                "command_type": c.command_type,
                "status": c.status,
                "sent_at": c.sent_at,
                "acked_at": c.acked_at,
            }
            for c in cmds.select_related("device")
        ]
        return Response(data)
