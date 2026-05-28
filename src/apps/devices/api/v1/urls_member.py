"""Member API URLs (SchoolAdmin + Member)"""
from django.urls import path

from apps.devices.api.v1.views.member import (
    MyDevicesView, MySchedulesView, MyDeviceStatusView, MyHolidaysView, MyBellLogsView,
    MyAlertsView, MemberHolidayCreateView, MemberHolidayDeleteView, MemberTodaySilentView,
    MemberAlertResolveView, MemberDeviceRingView, MemberDeviceEmergencyView,
    CommandStatusView, RecentCommandsView,
)
from apps.devices.api.v1.views.holiday_range import (
    MemberHolidayRangeListCreateView, MemberHolidayRangeDeleteView,
)

urlpatterns = [
    path("my-devices/", MyDevicesView.as_view(), name="member-my-devices"),
    path("my-schedules/", MySchedulesView.as_view(), name="member-my-schedules"),
    path("device-status/", MyDeviceStatusView.as_view(), name="member-device-status"),
    path("holidays/", MyHolidaysView.as_view(), name="member-holidays"),
    path("holidays/create/", MemberHolidayCreateView.as_view(), name="member-holiday-create"),
    path("holidays/<uuid:pk>/", MemberHolidayDeleteView.as_view(), name="member-holiday-delete"),
    path("holidays/today-silent/", MemberTodaySilentView.as_view(), name="member-today-silent"),
    path("holiday-ranges/", MemberHolidayRangeListCreateView.as_view(), name="member-holiday-ranges"),
    path("holiday-ranges/<uuid:pk>/", MemberHolidayRangeDeleteView.as_view(), name="member-holiday-range-delete"),
    path("bell-logs/", MyBellLogsView.as_view(), name="member-bell-logs"),
    path("alerts/", MyAlertsView.as_view(), name="member-alerts"),
    path("alerts/<uuid:pk>/resolve/", MemberAlertResolveView.as_view(), name="member-alert-resolve"),
    path("devices/<uuid:device_id>/ring/", MemberDeviceRingView.as_view(), name="member-device-ring"),
    path("devices/<uuid:device_id>/emergency/", MemberDeviceEmergencyView.as_view(), name="member-device-emergency"),
    path("commands/<uuid:msg_id>/status/", CommandStatusView.as_view(), name="member-command-status"),
    path("commands/recent/", RecentCommandsView.as_view(), name="member-commands-recent"),
]
