"""Admin-only device API URLs (SuperAdmin)"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.devices.api.v1.views.admin_device import AdminDeviceViewSet
from apps.devices.api.v1.views import (
    ScheduleViewSet,
    FirmwareVersionViewSet,
    OTABatchViewSet,
    DeviceLogViewSet,
)
from apps.devices.api.v1.views.holiday import HolidayViewSet
from apps.devices.api.v1.views.bell_log import BellLogViewSet
from apps.devices.api.v1.views.schedule_template import ScheduleTemplateViewSet
from apps.devices.api.v1.views.emergency import (
    EmergencyAlertListView,
    EmergencyRingAllView,
    EmergencyLockdownView,
    EmergencyCancelView,
)
from apps.devices.api.v1.views.mqtt_auth import MQTTAuthView, MQTTACLView

router = DefaultRouter()
router.register("devices", AdminDeviceViewSet, basename="admin-device")
router.register("schedules", ScheduleViewSet, basename="admin-schedule")
router.register("firmware", FirmwareVersionViewSet, basename="admin-firmware")
router.register("ota-batches", OTABatchViewSet, basename="admin-ota-batch")
router.register("device-logs", DeviceLogViewSet, basename="admin-device-log")
router.register("holidays", HolidayViewSet, basename="admin-holiday")
router.register("bell-logs", BellLogViewSet, basename="admin-bell-log")
router.register("schedule-templates", ScheduleTemplateViewSet, basename="admin-schedule-template")

urlpatterns = [
    path("", include(router.urls)),
    path("mqtt/auth/", MQTTAuthView.as_view(), name="mqtt_auth"),
    path("mqtt/acl/", MQTTACLView.as_view(), name="mqtt_acl"),
    path("emergency/", EmergencyAlertListView.as_view(), name="emergency-list"),
    path("emergency/ring-all/", EmergencyRingAllView.as_view(), name="emergency-ring-all"),
    path("emergency/lockdown/", EmergencyLockdownView.as_view(), name="emergency-lockdown"),
    path("emergency/cancel/", EmergencyCancelView.as_view(), name="emergency-cancel"),
]
