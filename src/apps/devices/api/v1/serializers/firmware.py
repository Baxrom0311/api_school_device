"""
Firmware Version Serializers
"""

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.devices.models import Device, FirmwareVersion


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
            "compatible_hw_versions",
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
            "compatible_hw_versions",
            "rollout_percentage",
        ]

    def validate_file(self, value):
        """Validate firmware file"""
        # Check file extension
        if not value.name.endswith(".bin"):
            raise serializers.ValidationError(_("Firmware file must have .bin extension"))

        # Check file size (ESP8266 has ~1MB flash for sketch)
        max_size = 1024 * 1024  # 1MB
        if value.size > max_size:
            raise serializers.ValidationError(_("Firmware file too large. Maximum size is 1MB"))

        return value

    def validate_compatible_hw_versions(self, value):
        """Validate hardware revisions as simple strings like 1.0 or 1.1."""
        if not isinstance(value, list):
            raise serializers.ValidationError(_("Compatible hardware versions must be a list"))
        cleaned = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise serializers.ValidationError(_("Hardware versions must be non-empty strings"))
            cleaned.append(item.strip())
        return cleaned

    def validate(self, attrs):
        """Cross-field validation"""
        min_version = attrs.get("min_version")
        version = attrs.get("version")

        if min_version and version:
            # Parse versions
            min_parts = [int(p) for p in min_version.split(".")]
            ver_parts = [int(p) for p in version.split(".")]

            if min_parts >= ver_parts:
                raise serializers.ValidationError(
                    {"min_version": _("Minimum version must be less than current version")}
                )

        return attrs


class FirmwareVersionListSerializer(serializers.ModelSerializer):
    """Minimal serializer for listing firmware versions"""

    class Meta:
        model = FirmwareVersion
        fields = [
            "id",
            "version",
            "is_stable",
            "compatible_hw_versions",
            "file_size",
            "created_at",
        ]
