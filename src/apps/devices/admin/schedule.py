"""
Schedule Admin
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from unfold.admin import ModelAdmin
from unfold.decorators import action, display

from apps.devices.models import Schedule
from apps.devices.services import mqtt_publisher


@admin.register(Schedule)
class ScheduleAdmin(ModelAdmin):
    """Schedule admin with sync actions"""
    
    list_display = [
        "device",
        "display_times_count",
        "is_active",
        "display_sync_status",
        "synced_at",
        "updated_at",
    ]
    list_filter = [
        "is_active",
        "sync_pending",
        "timezone",
    ]
    search_fields = [
        "device__device_id",
        "device__school_name",
    ]
    readonly_fields = [
        "synced_at",
        "sync_pending",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (_("Schedule"), {
            "fields": [
                "device",
                "times",
                "is_active",
                "timezone",
            ],
        }),
        (_("Sync Status"), {
            "fields": [
                "sync_pending",
                "synced_at",
            ],
        }),
        (_("Timestamps"), {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]
    
    @display(description=_("Times"))
    def display_times_count(self, obj):
        count = len(obj.times) if isinstance(obj.times, list) else 0
        return f"{count} times"
    
    @display(description=_("Sync"))
    def display_sync_status(self, obj):
        from django.utils.html import format_html
        if obj.sync_pending:
            return format_html(
                '<span style="color: #f59e0b;">⏳ Pending</span>'
            )
        else:
            return format_html(
                '<span style="color: #10b981;">✓ Synced</span>'
            )
    
    @action(description=_("Sync selected schedules to devices"))
    def sync_to_devices(self, request, queryset):
        """Push schedules to devices via MQTT"""
        success_count = 0
        for schedule in queryset.filter(is_active=True):
            if mqtt_publisher.send_schedule(
                schedule.device.device_id,
                schedule.times
            ):
                schedule.sync_pending = False
                schedule.synced_at = timezone.now()
                schedule.save(update_fields=["sync_pending", "synced_at"])
                success_count += 1
        
        self.message_user(
            request,
            f"Synced {success_count}/{queryset.count()} schedules"
        )
    
    actions = ["sync_to_devices"]
