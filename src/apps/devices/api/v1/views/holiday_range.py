from rest_framework import generics

from apps.devices.models.holiday_range import HolidayRange
from apps.devices.api.v1.serializers.holiday_range import HolidayRangeSerializer
from apps.shared.permissions import IsMember


def _trigger_holiday_sync():
    """Queue async holiday sync to all devices."""
    from apps.devices.tasks import sync_holidays_to_devices
    sync_holidays_to_devices.delay()


class MemberHolidayRangeListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/member/holiday-ranges/ — list and create holiday ranges."""
    serializer_class = HolidayRangeSerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        return HolidayRange.objects.filter(device__isnull=True).order_by("from_month", "from_day")

    def perform_create(self, serializer):
        serializer.save()
        _trigger_holiday_sync()


class MemberHolidayRangeDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/member/holiday-ranges/<id>/ — delete a holiday range."""
    serializer_class = HolidayRangeSerializer
    permission_classes = [IsMember]
    queryset = HolidayRange.objects.filter(device__isnull=True)

    def perform_destroy(self, instance):
        instance.delete()
        _trigger_holiday_sync()
