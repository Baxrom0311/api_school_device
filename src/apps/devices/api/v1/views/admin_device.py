"""Admin-only device viewset — enforces IsSuperAdmin on ALL actions.

The legacy DeviceViewSet has mixed permissions (some AllowAny for ESP32).
This subclass ensures the /api/v1/admin/ path is always admin-only.
"""

from apps.devices.api.v1.views.device import DeviceViewSet
from apps.shared.permissions import IsSuperAdmin


class AdminDeviceViewSet(DeviceViewSet):
    """All actions require SuperAdmin — no public endpoints on admin path."""

    def get_permissions(self):
        return [IsSuperAdmin()]
