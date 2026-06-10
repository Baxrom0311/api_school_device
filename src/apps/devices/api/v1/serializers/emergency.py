from rest_framework import serializers

from apps.devices.models.device_alert import DeviceAlert

ALERT_MESSAGES = {
    "panic": "🚨 Panic tugmasi bosildi",
    "lockdown": "🔒 Lockdown rejimi yoqildi",
    "emergency_ring": "🔔 Favqulodda qo'ng'iroq",
    "offline": "📡 Qurilma oflayn (24+ soat javob bermayapti)",
    "rtc_drift": "⏰ RTC vaqt farqi katta (batareya zaiflashgan bo'lishi mumkin)",
    "rtc_battery_dead": "🔋 RTC batareykasini almashtiring!",
    "schedule_stale": "📅 Jadval 7+ kun sinxronlanmagan",
}


class DeviceAlertSerializer(serializers.ModelSerializer):
    device_id = serializers.CharField(source="device.device_id", read_only=True, default=None)
    device_name = serializers.CharField(source="device.school_name", read_only=True, default="")
    message = serializers.SerializerMethodField()

    class Meta:
        model = DeviceAlert
        fields = ["id", "device_id", "device_name", "alert_type", "message", "resolved", "resolved_at", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_message(self, obj) -> str:
        return ALERT_MESSAGES.get(obj.alert_type, obj.alert_type)
