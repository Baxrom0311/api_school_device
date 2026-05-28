from rest_framework import serializers

from apps.devices.models.holiday import Holiday


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "name", "date", "recurring", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
