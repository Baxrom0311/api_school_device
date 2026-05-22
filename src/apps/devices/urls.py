from django.urls import path, include

app_name = "devices"

urlpatterns = [
    # Legacy: existing API (kept for backward compatibility)
    path("api/v1/", include("apps.devices.api.v1.urls")),
    # New separated endpoints
    path("api/v1/admin/", include("apps.devices.api.v1.urls_admin")),
    path("api/v1/member/", include("apps.devices.api.v1.urls_member")),
    path("api/v1/device/", include("apps.devices.api.v1.urls_device")),
]
