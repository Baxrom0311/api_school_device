from rest_framework import serializers

from apps.devices.models.bell_log import BellLog


class BellLogSerializer(serializers.ModelSerializer):
    device_id = serializers.CharField(source="device.device_id", read_only=True)

    class Meta:
        model = BellLog
        fields = ["id", "device", "device_id", "rang_at", "duration_ms", "trigger_source", "created_at"]
        read_only_fields = ["id", "created_at"]
