from rest_framework import serializers

from apps.devices.models.holiday_range import HolidayRange


class HolidayRangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = HolidayRange
        fields = ["id", "name", "from_month", "from_day", "to_month", "to_day", "created_at"]
        read_only_fields = ["id", "created_at"]
