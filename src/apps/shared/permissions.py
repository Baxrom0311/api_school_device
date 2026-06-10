from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsSuperAdmin(BasePermission):
    """Dashboard API — only ADMIN role users."""

    message = "Bu amal faqat super adminlar uchun ruxsat etilgan."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", None) in ("ADMIN", "SUPERADMIN")
        )


# Backward-compatible alias
IsAdminRole = IsSuperAdmin


class IsSchoolAdmin(BasePermission):
    """Member App — SCHOOL_ADMIN or ADMIN can write; all authenticated can read."""

    message = "Bu amal faqat maktab adminlari uchun ruxsat etilgan."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return getattr(request.user, "role", None) in ("ADMIN", "SCHOOL_ADMIN")


class IsMember(BasePermission):
    """Read-only access for regular members (USER role). Admins get full access."""

    message = "Oddiy foydalanuvchilar faqat ko'rish huquqiga ega."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if getattr(request.user, "role", None) in ("ADMIN", "SCHOOL_ADMIN"):
            return True
        return request.method in SAFE_METHODS


class IsDeviceOwner(BasePermission):
    """Object-level: user owns the device or is ADMIN."""

    message = "Bu qurilma sizga tegishli emas."

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) in ("ADMIN", "SUPERADMIN"):
            return True
        return getattr(obj, "owner", None) == request.user


class IsOwnerOrAdmin(BasePermission):
    """Object-level: user is the object owner or has ADMIN role."""

    message = "Bu amal faqat egasi yoki admin uchun ruxsat etilgan."

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) in ("ADMIN", "SUPERADMIN"):
            return True
        return obj == request.user or getattr(obj, "user", None) == request.user
