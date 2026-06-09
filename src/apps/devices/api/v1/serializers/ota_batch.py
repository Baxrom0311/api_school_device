"""
OTA Batch Serializers - Handle batch OTA operations.
"""
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.devices.models import OTABatch, OTABatchDevice, Device, FirmwareVersion


class OTABatchDeviceSerializer(serializers.ModelSerializer):
    """Serializer for individual device in OTA batch"""
    device_id = serializers.CharField(source="device.device_id", read_only=True)
    school_name = serializers.CharField(source="device.school_name", read_only=True)
    current_version = serializers.CharField(
        source="device.firmware_version",
        read_only=True
    )
    
    class Meta:
        model = OTABatchDevice
        fields = [
            "id",
            "device",
            "device_id",
            "school_name",
            "status",
            "previous_version",
            "current_version",
            "notified_at",
            "completed_at",
            "error_message",
            "retry_count",
        ]
        read_only_fields = [
            "id",
            "status",
            "previous_version",
            "notified_at",
            "completed_at",
            "error_message",
            "retry_count",
        ]


class OTABatchSerializer(serializers.ModelSerializer):
    """Full OTA batch serializer"""
    firmware_version = serializers.CharField(
        source="firmware.version",
        read_only=True
    )
    progress_percentage = serializers.FloatField(read_only=True)
    pending_count = serializers.IntegerField(read_only=True)
    created_by_email = serializers.CharField(
        source="created_by.email",
        read_only=True,
        allow_null=True
    )
    
    class Meta:
        model = OTABatch
        fields = [
            "id",
            "name",
            "firmware",
            "firmware_version",
            "status",
            "devices_per_hour",
            "scheduled_at",
            "started_at",
            "completed_at",
            "total_devices",
            "success_count",
            "failure_count",
            "pending_count",
            "progress_percentage",
            "created_by",
            "created_by_email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "started_at",
            "completed_at",
            "total_devices",
            "success_count",
            "failure_count",
            "created_at",
            "updated_at",
        ]


class OTABatchCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new OTA batch.
    
    WHY custom serializer:
    - Need to accept device_ids list and create OTABatchDevice entries
    - Validate firmware compatibility with selected devices
    - Set up batch with proper initial state
    """
    name = serializers.CharField(max_length=255)
    firmware_id = serializers.UUIDField()
    device_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=500,
        help_text=_("List of device IDs to include in batch"),
    )
    devices_per_hour = serializers.IntegerField(
        min_value=1,
        max_value=1000,
        default=100,
    )
    scheduled_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
    )
    
    def validate_firmware_id(self, value):
        """Validate firmware exists and is stable"""
        try:
            firmware = FirmwareVersion.objects.get(id=value)
        except FirmwareVersion.DoesNotExist:
            raise serializers.ValidationError(_("Firmware version not found"))
        
        if not firmware.is_stable:
            raise serializers.ValidationError(
                _("Cannot create batch with unstable firmware. Mark as stable first.")
            )
        
        return value
    
    def validate_device_ids(self, value):
        """Validate all devices exist and are active"""
        devices = Device.objects.filter(id__in=value)
        
        if devices.count() != len(value):
            found_ids = set(devices.values_list("id", flat=True))
            missing = set(value) - found_ids
            raise serializers.ValidationError(
                f"Devices not found: {list(missing)}"
            )
        
        # Check for devices already in pending OTA
        from apps.devices.models.ota_batch import OTABatchStatus
        pending_devices = OTABatchDevice.objects.filter(
            device_id__in=value,
            batch__status__in=[OTABatchStatus.PENDING, OTABatchStatus.IN_PROGRESS]
        ).values_list("device_id", flat=True)
        
        if pending_devices:
            raise serializers.ValidationError(
                f"Devices already in pending OTA: {list(pending_devices)}"
            )
        
        return value
    
    def validate(self, attrs):
        """Cross-validate firmware compatibility"""
        firmware = FirmwareVersion.objects.get(id=attrs["firmware_id"])
        devices = Device.objects.filter(id__in=attrs["device_ids"])
        
        incompatible = []
        for device in devices:
            if not firmware.can_upgrade_from(device.firmware_version):
                incompatible.append({
                    "device_id": device.device_id,
                    "current_version": device.firmware_version,
                    "min_required": firmware.min_version,
                })
            elif not firmware.supports_hardware(device.hw_version):
                incompatible.append({
                    "device_id": device.device_id,
                    "hw_version": device.hw_version,
                    "compatible_hw_versions": firmware.compatible_hw_versions,
                })
        
        if incompatible:
            raise serializers.ValidationError({
                "device_ids": _(
                    f"{len(incompatible)} devices incompatible with firmware."
                ),
                "incompatible_devices": incompatible[:10],  # Show first 10
            })
        
        return attrs
    
    def create(self, validated_data):
        """Create OTA batch with devices"""
        from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus
        
        firmware = FirmwareVersion.objects.get(id=validated_data["firmware_id"])
        devices = Device.objects.filter(id__in=validated_data["device_ids"])
        
        # Create batch
        batch = OTABatch.objects.create(
            name=validated_data["name"],
            firmware=firmware,
            status=OTABatchStatus.PENDING,
            devices_per_hour=validated_data["devices_per_hour"],
            scheduled_at=validated_data.get("scheduled_at"),
            total_devices=devices.count(),
            created_by=self.context["request"].user if self.context.get("request") else None,
        )
        
        # Create batch device entries
        batch_devices = [
            OTABatchDevice(
                batch=batch,
                device=device,
                status=OTADeviceStatus.PENDING,
                previous_version=device.firmware_version,
            )
            for device in devices
        ]
        OTABatchDevice.objects.bulk_create(batch_devices)
        
        return batch


class OTABatchActionSerializer(serializers.Serializer):
    """Serializer for OTA batch actions (start, cancel, retry)"""
    action = serializers.ChoiceField(
        choices=["start", "cancel", "retry_failed"],
        help_text=_("Action to perform on batch"),
    )
