from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """Dashboard API — only ADMIN role users."""
    message = "Bu amal faqat super adminlar uchun ruxsat etilgan."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", None) == "ADMIN"
        )


# Backward-compatible alias
IsAdminRole = IsSuperAdmin


class IsSchoolAdmin(BasePermission):
    """Member App — authenticated users who own devices."""
    message = "Bu amal faqat maktab adminlari uchun ruxsat etilgan."

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class IsDeviceOwner(BasePermission):
    """Object-level: user owns the device or is ADMIN."""
    message = "Bu qurilma sizga tegishli emas."

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) == "ADMIN":
            return True
        return getattr(obj, "owner", None) == request.user


class IsOwnerOrAdmin(BasePermission):
    """Object-level: user is the object owner or has ADMIN role."""
    message = "Bu amal faqat egasi yoki admin uchun ruxsat etilgan."

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) == "ADMIN":
            return True
        return obj == request.user or getattr(obj, "user", None) == request.user
