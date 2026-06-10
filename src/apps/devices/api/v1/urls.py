"""
API v1 URL Configuration for Devices App
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.devices.api.v1.views import (
    DeviceLogViewSet,
    DeviceViewSet,
    FirmwareVersionViewSet,
    OTABatchViewSet,
    ScheduleViewSet,
)
from apps.devices.api.v1.views.mqtt_auth import MQTTACLView, MQTTAuthView

router = DefaultRouter()
router.register("devices", DeviceViewSet, basename="device")
router.register("schedules", ScheduleViewSet, basename="schedule")
router.register("firmware", FirmwareVersionViewSet, basename="firmware")
router.register("ota-batches", OTABatchViewSet, basename="ota-batch")
router.register("device-logs", DeviceLogViewSet, basename="device-log")

urlpatterns = [
    path("", include(router.urls)),
    # EMQX HTTP auth plugin endpoints
    path("mqtt/auth/", MQTTAuthView.as_view(), name="mqtt_auth"),
    path("mqtt/acl/", MQTTACLView.as_view(), name="mqtt_acl"),
]
