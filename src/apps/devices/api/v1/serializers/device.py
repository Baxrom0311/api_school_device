"""
Device Serializers - Handles device data serialization/deserialization.

WHY multiple serializers:
1. List view needs minimal data (performance for 10K+ devices)
2. Detail view needs all fields
3. Create has different validation than update
4. Nested schedule for convenience
5. Credentials serializer for IoT developers
6. API Key serializer for device provisioning
"""
import os
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.devices.models import Device, Schedule


class DeviceAPIKeySerializer(serializers.ModelSerializer):
    """
    Serializer for device API key (for provisioning/sales).
    
    Shows API key which is used for device authentication.
    Each sold device gets a unique API key.
    """
    class Meta:
        model = Device
        fields = [
            "id",
            "device_id",
            "api_key",
            "registration_status",
            "registered_at",
        ]
        read_only_fields = ["api_key", "registration_status", "registered_at"]


class DeviceCredentialsSerializer(serializers.ModelSerializer):
    """
    Serializer for IoT device credentials.
    
    Used by IoT developers and Frontend to get MQTT connection details.
    mqtt_password is only shown as raw value on creation/regeneration
    (via _raw_mqtt_password attribute). Otherwise shows "***" placeholder.
    """
    mqtt_broker = serializers.SerializerMethodField()
    mqtt_port = serializers.SerializerMethodField()
    mqtt_use_tls = serializers.SerializerMethodField()
    mqtt_password = serializers.SerializerMethodField()
    topics = serializers.SerializerMethodField()
    
    class Meta:
        model = Device
        fields = [
            "id",
            "device_id",
            "school_name",
            "api_key",
            "registration_status",
            "mqtt_broker",
            "mqtt_port",
            "mqtt_username",
            "mqtt_password",
            "mqtt_use_tls",
            "topics",
        ]
        read_only_fields = ["api_key", "mqtt_username", "mqtt_password", "registration_status"]
    
    def get_mqtt_password(self, obj) -> str:
        # Return raw password only if available (just created/regenerated)
        raw = getattr(obj, '_raw_mqtt_password', None)
        if raw:
            return raw
        return "***"
    
    def get_mqtt_broker(self, obj) -> str:
        return os.getenv("MQTT_BROKER_HOST", "localhost")
    
    def get_mqtt_port(self, obj) -> int:
        return int(os.getenv("MQTT_BROKER_PORT", "1883"))
    
    def get_mqtt_use_tls(self, obj) -> bool:
        return os.getenv("MQTT_USE_TLS", "false").lower() == "true"
    
    def get_topics(self, obj) -> dict:
        return {
            "command": f"devices/{obj.device_id}/command",
            "schedule": f"devices/{obj.device_id}/schedule",
            "config": f"devices/{obj.device_id}/config",
            "status": f"devices/{obj.device_id}/status",
            "ota_status": f"devices/{obj.device_id}/ota/status",
        }


class ScheduleNestedSerializer(serializers.ModelSerializer):
    """Minimal schedule info for device list/detail"""
    times_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Schedule
        fields = ["id", "times", "times_count", "is_active", "sync_pending"]


class DeviceSerializer(serializers.ModelSerializer):
    """Base device serializer"""
    
    class Meta:
        model = Device
        fields = [
            "id",
            "device_id",
            "school_name",
            "address",
            "description",
            "status",
            "firmware_version",
            "rtc_synced",
            "last_seen",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "last_seen"]


class DeviceListSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for list views.
    
    WHY: Loading 10K devices with all fields is slow.
    This returns only what's needed for a dashboard/table.
    """
    has_schedule = serializers.SerializerMethodField()
    
    class Meta:
        model = Device
        fields = [
            "id",
            "device_id",
            "school_name",
            "status",
            "firmware_version",
            "rtc_synced",
            "has_schedule",
            "registration_status",
            "registered_at",
            "last_seen",
            "created_at",
            "updated_at",
        ]
    
    def get_has_schedule(self, obj) -> bool:
        return hasattr(obj, "schedule")


class DeviceDetailSerializer(serializers.ModelSerializer):
    """
    Full serializer for detail views.
    Includes nested schedule, diagnostic info, and registration status.
    """
    schedule = ScheduleNestedSerializer(read_only=True)
    needs_ota_update = serializers.BooleanField(read_only=True)
    target_firmware_version = serializers.CharField(
        source="target_firmware.version",
        read_only=True,
        allow_null=True,
    )
    is_registered = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Device
        fields = [
            "id",
            "device_id",
            "school_name",
            "address",
            "description",
            "status",
            "firmware_version",
            "target_firmware",
            "target_firmware_version",
            "needs_ota_update",
            "rtc_synced",
            "created_at",
            "updated_at",
            "last_seen",
            "schedule",
            "api_key",
            "registration_status",
            "registered_at",
            "is_registered",
        ]
        read_only_fields = [
            "id",
            "firmware_version",
            "rtc_synced",
            "created_at",
            "updated_at",
            "last_seen",
            "api_key",
            "registration_status",
            "registered_at",
            "is_registered",
        ]


class DeviceCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating new devices.
    
    WHY separate: Device creation has specific validation,
    and we may want to auto-generate MQTT credentials.
    """
    
    class Meta:
        model = Device
        fields = [
            "device_id",
            "school_name",
            "address",
            "description",
            "status",
        ]
    
    def validate_device_id(self, value):
        """Ensure device_id is unique and normalize MAC format."""
        import re
        normalized = re.sub(r'[:\-]', '', value.strip()).upper()
        if re.fullmatch(r'[0-9A-F]{12}', normalized):
            value = normalized
        if Device.objects.filter(device_id=value).exists():
            raise serializers.ValidationError(
                _("Device with this ID already exists")
            )
        return value
    

class DeviceBulkActionSerializer(serializers.Serializer):
    """Serializer for bulk device actions"""
    device_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100,
        help_text=_("List of device IDs to perform action on"),
    )
    
    def validate_device_ids(self, value):
        """Verify all device IDs exist"""
        existing = set(
            Device.objects.filter(id__in=value).values_list("id", flat=True)
        )
        missing = set(value) - existing
        if missing:
            raise serializers.ValidationError(
                f"Devices not found: {list(missing)}"
            )
        return value


class DeviceRingSerializer(serializers.Serializer):
    """Serializer for ring command"""
    duration = serializers.IntegerField(
        min_value=1,
        max_value=60,
        default=5,
        help_text=_("Ring duration in seconds"),
    )


class DeviceBulkOTASerializer(serializers.Serializer):
    """Serializer for bulk OTA update"""
    device_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100,
        help_text=_("List of device IDs to update"),
    )
    firmware_id = serializers.UUIDField(
        help_text=_("Firmware version ID to install"),
    )
    immediate = serializers.BooleanField(
        default=True,
        help_text=_("Send updates immediately (no throttling)"),
    )


class DeviceStatsSerializer(serializers.Serializer):
    """Serializer for device statistics response"""
    total_devices = serializers.IntegerField()
    registered_devices = serializers.IntegerField()
    pending_devices = serializers.IntegerField()
    rtc_errors = serializers.IntegerField()
    firmware_versions = serializers.DictField(
        child=serializers.IntegerField(),
        help_text=_("Count of devices per firmware version"),
    )


# ============== Auto-Registration Serializers ==============

class DeviceAutoRegisterSerializer(serializers.Serializer):
    """
    Serializer for ESP32 auto-registration request.
    
    ESP32 sends its MAC address, backend creates/returns device.
    """
    device_id = serializers.CharField(
        max_length=17,
        help_text=_("Device MAC address (hex, with or without separators)"),
    )
    firmware_version = serializers.CharField(
        max_length=20,
        required=False,
        default="0.0.0",
        help_text=_("Current firmware version"),
    )

    def validate_device_id(self, value: str) -> str:
        import re
        normalized = re.sub(r'[:\-]', '', value).upper()
        if not re.fullmatch(r'[0-9A-F]{12}', normalized):
            raise serializers.ValidationError("Invalid MAC address format.")
        return normalized


class DeviceAutoRegisterResponseSerializer(serializers.Serializer):
    """Response for auto-registration"""
    status = serializers.CharField()
    message = serializers.CharField()
    device_id = serializers.CharField()
    registration_status = serializers.CharField()
    # Only included if registered
    credentials = DeviceCredentialsSerializer(required=False, allow_null=True)


class DeviceApproveSerializer(serializers.Serializer):
    """
    Serializer for admin to approve a pending device.
    
    Admin provides school info when approving.
    """
    school_name = serializers.CharField(
        max_length=255,
        help_text=_("Name of the school"),
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=_("School address"),
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=_("Additional notes"),
    )


class DeviceClaimSerializer(serializers.Serializer):
    """
    Serializer for user to claim a device by MAC address.
    
    User provides MAC address and optional device name.
    Device must exist and be unregistered.
    
    IMPORTANT: Each user can only have ONE device.
    """
    device_id = serializers.CharField(
        max_length=64,
        help_text=_("Device MAC address (from sticker on device)"),
    )
    device_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text=_("Custom name for the device (e.g., 'Main Bell')"),
    )

    def validate_device_id(self, value):
        """Check if device exists and is unregistered"""
        # Normalize MAC address (remove colons, uppercase)
        normalized = value.replace(":", "").replace("-", "").upper()
        
        try:
            device = Device.objects.get(device_id__iexact=value) 
        except Device.DoesNotExist:
            try:
                device = Device.objects.get(device_id__iexact=normalized)
            except Device.DoesNotExist:
                raise serializers.ValidationError(
                    _("Qurilma topilmadi. MAC address to'g'ri kiritilganini tekshiring.")
                )
        
        if device.registration_status == "registered":
            raise serializers.ValidationError(
                _("Bu qurilma allaqachon ro'yxatdan o'tgan.")
            )
        
        return device.device_id

    def claim(self, user):
        """Claim the device for the user"""
        from django.db import transaction

        with transaction.atomic():
            # Check if user already has a device
            if Device.objects.filter(owner=user).exists():
                raise serializers.ValidationError({
                    "device_id": _("Sizda allaqachon qurilma mavjud. Har bir foydalanuvchi faqat bitta qurilmaga ega bo'lishi mumkin.")
                })

            device_id = self.validated_data["device_id"]
            device_name = self.validated_data.get("device_name", "")

            device = Device.objects.select_for_update().get(device_id=device_id)

            if device.registration_status == "registered":
                raise serializers.ValidationError({
                    "device_id": _("Bu qurilma allaqachon ro'yxatdan o'tgan.")
                })

            device.register_device(owner=user, device_name=device_name)

        return device


class DeviceClaimResponseSerializer(serializers.ModelSerializer):
    """Response for device claim"""
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    
    class Meta:
        model = Device
        fields = [
            "id",
            "device_id",
            "school_name",
            "status",
            "registration_status",
            "registered_at",
            "owner_email",
        ]
