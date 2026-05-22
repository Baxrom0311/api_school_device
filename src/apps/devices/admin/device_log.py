from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.devices.models.device_log import DeviceLog


@admin.register(DeviceLog)
class DeviceLogAdmin(ModelAdmin):
    list_display = ["device", "level", "source", "short_message", "created_at"]
    list_filter = ["level", "source", "created_at"]
    search_fields = ["device__device_id", "device__school_name", "message"]
    readonly_fields = ["device", "level", "source", "message", "metadata", "created_at"]
    list_per_page = 100
    ordering = ["-created_at"]

    def short_message(self, obj):
        return obj.message[:80] if obj.message else ""
    short_message.short_description = _("Message")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
