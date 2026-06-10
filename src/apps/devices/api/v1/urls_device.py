"""Device API URLs (ESP32 device endpoints, API key auth)"""

from django.urls import path

from apps.devices.api.v1.views.device_endpoints import (
    DeviceActivateView,
    DeviceAutoRegisterView,
    DeviceCredentialsView,
    DeviceScheduleView,
)

urlpatterns = [
    path("auto-register/", DeviceAutoRegisterView.as_view(), name="device-auto-register"),
    path("activate/", DeviceActivateView.as_view(), name="device-activate"),
    path("credentials/", DeviceCredentialsView.as_view(), name="device-credentials"),
    path("schedule/", DeviceScheduleView.as_view(), name="device-schedule"),
]
