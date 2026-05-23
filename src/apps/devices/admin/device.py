"""
Device Admin - Unfold-compatible admin for device management.

WHY Unfold:
- Modern UI for IoT dashboard
- Better support for actions and filters
- Inline editing support
"""
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from unfold.admin import ModelAdmin
from unfold.decorators import action, display

from apps.devices.models import Device, Schedule
from apps.devices.services import mqtt_publisher


class ScheduleInline(admin.TabularInline):
    """Inline schedule editing within device admin"""
    model = Schedule
    extra = 0
    fields = ["times", "is_active", "sync_pending", "synced_at"]
    readonly_fields = ["sync_pending", "synced_at"]
    can_delete = False
    max_num = 1


@admin.register(Device)
class DeviceAdmin(ModelAdmin):
    """
    Device admin with custom actions and displays.
    
    Features:
    - Status indicators (registration status, RTC health)
    - Quick actions (ring, restart, sync schedule)
    - Filtering and search for large device lists
    """
    
    list_display = [
        "device_id",
        "school_name",
        "display_status",
        "display_registration_status",
        "display_rtc_status",
        "firmware_version",
        "registered_at",
    ]
    list_filter = [
        "status",
        "registration_status",
        "rtc_synced",
        "firmware_version",
        "created_at",
    ]
    search_fields = [
        "device_id",
        "school_name",
        "address",
    ]
    readonly_fields = [
        "firmware_version",
        "rtc_synced",
        "registered_at",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (_("Device Info"), {
            "fields": [
                "device_id",
                "school_name",
                "address",
                "description",
                "status",
            ],
        }),
        (_("Registration"), {
            "fields": [
                "registration_status",
                "registered_at",
                "firmware_version",
                "target_firmware",
            ],
        }),
        (_("RTC Status"), {
            "fields": [
                "rtc_synced",
            ],
            "classes": ["collapse"],
        }),
        (_("Timestamps"), {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]
    inlines = [ScheduleInline]
    list_per_page = 50
    ordering = ["-created_at"]
    
    @display(
        description=_("Status"),
        label={
            "active": "success",
            "inactive": "warning",
            "maintenance": "info",
            "decommissioned": "danger",
        },
    )
    def display_status(self, obj):
        return obj.status
    
    @display(description=_("Registration"))
    def display_registration_status(self, obj):
        if obj.registration_status == "registered":
            return format_html(
                '<span style="color: #10b981;">● Registered</span>'
            )
        elif obj.registration_status == "pending":
            return format_html(
                '<span style="color: #f59e0b;">● Pending</span>'
            )
        else:
            return format_html(
                '<span style="color: #6b7280;">● Unregistered</span>'
            )
    
    @display(description=_("RTC"))
    def display_rtc_status(self, obj):
        if obj.rtc_synced:
            return format_html(
                '<span style="color: #10b981;">✓ OK</span>'
            )
        else:
            return format_html(
                '<span style="color: #ef4444;">✗ Error</span>'
            )
    
    @action(description=_("Ring selected devices"))
    def ring_devices(self, request, queryset):
        """Send ring command to selected devices"""
        success_count = 0
        for device in queryset:
            if mqtt_publisher.ring(device.device_id):
                success_count += 1
        
        self.message_user(
            request,
            f"Ring command sent to {success_count}/{queryset.count()} devices"
        )
    
    @action(description=_("Restart selected devices"))
    def restart_devices(self, request, queryset):
        """Send restart command to selected devices"""
        success_count = 0
        for device in queryset:
            if mqtt_publisher.send_restart(device.device_id):
                success_count += 1
        
        self.message_user(
            request,
            f"Restart command sent to {success_count}/{queryset.count()} devices"
        )
    
    @action(description=_("Sync schedules to selected devices"))
    def sync_schedules(self, request, queryset):
        """Push schedules to selected devices"""
        success_count = 0
        for device in queryset:
            if hasattr(device, "schedule") and device.schedule.is_active:
                if mqtt_publisher.send_schedule(
                    device.device_id,
                    device.schedule.times,
                    version=device.schedule.version,
                ):
                    device.schedule.sync_pending = False
                    device.schedule.synced_at = timezone.now()
                    device.schedule.save(update_fields=["sync_pending", "synced_at"])
                    success_count += 1
        
        self.message_user(
            request,
            f"Schedules synced to {success_count}/{queryset.count()} devices"
        )
    
    @action(description=_("Approve registration"))
    def approve_registration(self, request, queryset):
        """Approve pending device registrations"""
        count = queryset.filter(registration_status="pending").update(
            registration_status="registered",
            registered_at=timezone.now()
        )
        self.message_user(request, f"Approved {count} devices")
    
    actions = [
        "ring_devices",
        "restart_devices",
        "sync_schedules",
        "approve_registration",
    ]
