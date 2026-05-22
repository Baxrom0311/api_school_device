"""Member views - endpoints for SchoolAdmin and Member roles."""
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.devices.models import Device, Schedule
from apps.devices.api.v1.serializers.device import DeviceListSerializer
from apps.devices.api.v1.serializers.schedule import ScheduleSerializer


class MyDevicesView(generics.ListAPIView):
    """GET /api/v1/member/my-devices/ — devices owned by current user."""
    serializer_class = DeviceListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Device.objects.filter(
            owner=self.request.user
        ).select_related("schedule").order_by("-created_at")


class MySchedulesView(generics.ListAPIView):
    """GET /api/v1/member/my-schedules/ — schedules for current user's devices."""
    serializer_class = ScheduleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Schedule.objects.filter(
            device__owner=self.request.user
        ).select_related("device").order_by("-updated_at")
