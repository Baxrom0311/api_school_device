"""Admin-only device API URLs (SuperAdmin)"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.devices.api.v1.views import (
    DeviceViewSet,
    ScheduleViewSet,
    FirmwareVersionViewSet,
    OTABatchViewSet,
    DeviceLogViewSet,
)
from apps.devices.api.v1.views.mqtt_auth import MQTTAuthView, MQTTACLView

router = DefaultRouter()
router.register("devices", DeviceViewSet, basename="admin-device")
router.register("schedules", ScheduleViewSet, basename="admin-schedule")
router.register("firmware", FirmwareVersionViewSet, basename="admin-firmware")
router.register("ota-batches", OTABatchViewSet, basename="admin-ota-batch")
router.register("device-logs", DeviceLogViewSet, basename="admin-device-log")

urlpatterns = [
    path("", include(router.urls)),
    path("mqtt/auth/", MQTTAuthView.as_view(), name="mqtt_auth"),
    path("mqtt/acl/", MQTTACLView.as_view(), name="mqtt_acl"),
]
