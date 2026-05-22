"""
Firmware Version Serializers
"""
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.devices.models import FirmwareVersion, Device


class FirmwareVersionSerializer(serializers.ModelSerializer):
    """Full firmware version serializer"""
    download_url = serializers.CharField(read_only=True)
    devices_count = serializers.SerializerMethodField()
    targeted_devices_count = serializers.SerializerMethodField()
    
    class Meta:
        model = FirmwareVersion
        fields = [
            "id",
            "version",
            "file",
            "checksum",
            "file_size",
            "changelog",
            "is_stable",
            "min_version",
            "rollout_percentage",
            "download_url",
            "devices_count",
            "targeted_devices_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "checksum",
            "file_size",
            "created_at",
            "updated_at",
        ]
    
    def get_devices_count(self, obj) -> int:
        """Count of devices currently on this version"""
        return Device.objects.filter(firmware_version=obj.version).count()
    
    def get_targeted_devices_count(self, obj) -> int:
        """Count of devices targeted to update to this version"""
        return obj.targeted_devices.count()


class FirmwareVersionCreateSerializer(serializers.ModelSerializer):
    """Serializer for uploading new firmware"""
    
    class Meta:
        model = FirmwareVersion
        fields = [
            "version",
            "file",
            "changelog",
            "is_stable",
            "min_version",
            "rollout_percentage",
        ]
    
    def validate_file(self, value):
        """Validate firmware file"""
        # Check file extension
        if not value.name.endswith(".bin"):
            raise serializers.ValidationError(
                _("Firmware file must have .bin extension")
            )
        
        # Check file size (ESP8266 has ~1MB flash for sketch)
        max_size = 1024 * 1024  # 1MB
        if value.size > max_size:
            raise serializers.ValidationError(
                _("Firmware file too large. Maximum size is 1MB")
            )
        
        return value
    
    def validate(self, attrs):
        """Cross-field validation"""
        min_version = attrs.get("min_version")
        version = attrs.get("version")
        
        if min_version and version:
            # Parse versions
            min_parts = [int(p) for p in min_version.split(".")]
            ver_parts = [int(p) for p in version.split(".")]
            
            if min_parts >= ver_parts:
                raise serializers.ValidationError({
                    "min_version": _("Minimum version must be less than current version")
                })
        
        return attrs


class FirmwareVersionListSerializer(serializers.ModelSerializer):
    """Minimal serializer for listing firmware versions"""
    
    class Meta:
        model = FirmwareVersion
        fields = [
            "id",
            "version",
            "is_stable",
            "file_size",
            "created_at",
        ]
