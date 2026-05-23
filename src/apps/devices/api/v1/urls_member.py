"""Member API URLs (SchoolAdmin + Member)"""
from django.urls import path

from apps.devices.api.v1.views.member import MyDevicesView, MySchedulesView, MyDeviceStatusView

urlpatterns = [
    path("my-devices/", MyDevicesView.as_view(), name="member-my-devices"),
    path("my-schedules/", MySchedulesView.as_view(), name="member-my-schedules"),
    path("device-status/", MyDeviceStatusView.as_view(), name="member-device-status"),
]
