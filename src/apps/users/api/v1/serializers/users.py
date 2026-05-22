from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class AdminUserListSerializer(serializers.ModelSerializer):
    """Serializer for listing users (admin view)."""
    
    devices_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "avatar",
            "role",
            "is_active",
            "is_verified",
            "organization_name",
            "devices_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_devices_count(self, obj):
        """Get the count of devices owned by this user."""
        return obj.devices.count() if hasattr(obj, 'devices') else 0


class AdminUserDetailSerializer(serializers.ModelSerializer):
    """Serializer for user detail (admin view)."""
    
    devices = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "avatar",
            "role",
            "is_active",
            "is_verified",
            "organization_name",
            "devices",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "email", "created_at", "updated_at"]

    def get_devices(self, obj):
        """Get list of devices owned by this user."""
        from apps.devices.api.v1.serializers import DeviceSerializer
        if hasattr(obj, 'devices'):
            return DeviceSerializer(obj.devices.all(), many=True).data
        return []


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user (admin view)."""

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "role",
            "is_active",
            "is_verified",
            "organization_name",
        ]


class AdminSetPasswordSerializer(serializers.Serializer):
    """Serializer for admin setting user password."""
    
    new_password = serializers.CharField(required=True, write_only=True, min_length=7)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        """Validate passwords match."""
        if attrs.get("new_password") != attrs.get("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Parollar mos kelmaydi."})
        return attrs
