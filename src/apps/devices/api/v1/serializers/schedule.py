"""
Schedule Serializers - Handle schedule CRUD operations.

WHY:
- Validates time format (HH:MM)
- Triggers MQTT sync on update
- Supports partial updates
"""
import re
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.devices.models import Schedule, Device


TIME_PATTERN = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


class ScheduleSerializer(serializers.ModelSerializer):
    """Full schedule serializer"""
    device_id = serializers.CharField(source="device.device_id", read_only=True)
    device_name = serializers.CharField(source="device.school_name", read_only=True)
    times_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Schedule
        fields = [
            "id",
            "device",
            "device_id",
            "device_name",
            "times",
            "times_count",
            "days_mask",
            "bell_duration",
            "is_active",
            "timezone",
            "version",
            "synced_at",
            "sync_pending",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "version",
            "synced_at",
            "sync_pending",
            "created_at",
            "updated_at",
        ]


class ScheduleUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating schedules.
    
    WHY separate:
    - Device field should not be changeable
    - Need custom validation for times
    - Triggers MQTT push on save
    """
    
    class Meta:
        model = Schedule
        fields = ["times", "days_mask", "bell_duration", "is_active", "timezone"]
    
    def validate_days_mask(self, value):
        """Validate days_mask is 0-127"""
        if not (0 <= value <= 127):
            raise serializers.ValidationError(_("days_mask must be between 0 and 127"))
        return value
    
    def validate_bell_duration(self, value):
        """Validate bell_duration is between 500ms and 30000ms"""
        if not (500 <= value <= 30000):
            raise serializers.ValidationError(_("bell_duration must be between 500 and 30000 ms"))
        return value
    
    def validate_times(self, value):
        """Validate all times are in HH:MM format"""
        if not isinstance(value, list):
            raise serializers.ValidationError(_("Times must be a list"))
        
        if len(value) > 100:
            raise serializers.ValidationError(
                _("Maximum 100 times allowed per schedule")
            )
        
        errors = []
        seen = set()
        
        for i, time in enumerate(value):
            if not isinstance(time, str):
                errors.append(f"Time at index {i} must be a string")
                continue
                
            if not TIME_PATTERN.match(time):
                errors.append(
                    f"Invalid time format at index {i}: '{time}'. Use HH:MM (24h)"
                )
                continue
            
            if time in seen:
                errors.append(f"Duplicate time: {time}")
            seen.add(time)
        
        if errors:
            raise serializers.ValidationError(errors)
        
        # Sort times chronologically
        return sorted(value)
    
    def update(self, instance, validated_data):
        """Update schedule and mark for sync"""
        # Check if times, days_mask, or bell_duration changed
        sync_needed = (
            ("times" in validated_data and validated_data["times"] != instance.times) or
            ("days_mask" in validated_data and validated_data["days_mask"] != instance.days_mask) or
            ("bell_duration" in validated_data and validated_data["bell_duration"] != instance.bell_duration)
        )
        
        instance = super().update(instance, validated_data)
        
        if sync_needed:
            instance.sync_pending = True
            instance.save(update_fields=["sync_pending"])
        
        return instance


class ScheduleCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating schedule for a device that doesn't have one"""
    device = serializers.PrimaryKeyRelatedField(
        queryset=Device.objects.all()
    )
    
    class Meta:
        model = Schedule
        fields = ["device", "times", "days_mask", "bell_duration", "is_active", "timezone"]
    
    def validate_device(self, value):
        """Check device doesn't already have a schedule and user owns it"""
        request = self.context.get("request")
        if request and getattr(request.user, "role", None) not in ("ADMIN", "SCHOOL_ADMIN"):
            if value.owner != request.user:
                raise serializers.ValidationError(
                    _("You can only create schedules for your own devices")
                )
        if Schedule.objects.filter(device=value).exists():
            raise serializers.ValidationError(
                _("This device already has a schedule")
            )
        return value
    
    def validate_times(self, value):
        """Reuse validation from update serializer"""
        serializer = ScheduleUpdateSerializer()
        return serializer.validate_times(value)


class ScheduleBulkSyncSerializer(serializers.Serializer):
    """Serializer for bulk schedule sync action"""
    schedule_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text=_("Specific schedule IDs to sync. If empty, syncs all pending."),
    )
