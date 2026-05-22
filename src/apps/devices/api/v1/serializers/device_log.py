from rest_framework import serializers

from apps.devices.models.device_log import DeviceLog


class DeviceLogSerializer(serializers.ModelSerializer):
    device_id = serializers.CharField(source="device.device_id", read_only=True)

    class Meta:
        model = DeviceLog
        fields = ["id", "device", "device_id", "level", "source", "message", "metadata", "created_at"]
        read_only_fields = ["id", "created_at"]
