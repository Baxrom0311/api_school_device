"""
Firmware Admin
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action, display

from apps.devices.models import FirmwareVersion, Device


@admin.register(FirmwareVersion)
class FirmwareVersionAdmin(ModelAdmin):
    """Firmware version admin"""
    
    list_display = [
        "version",
        "display_stable_status",
        "display_file_size",
        "display_adoption",
        "created_at",
    ]
    list_filter = [
        "is_stable",
        "created_at",
    ]
    search_fields = ["version", "changelog"]
    readonly_fields = [
        "checksum",
        "file_size",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (_("Version Info"), {
            "fields": [
                "version",
                "file",
                "changelog",
            ],
        }),
        (_("Release Settings"), {
            "fields": [
                "is_stable",
                "min_version",
                "rollout_percentage",
            ],
        }),
        (_("File Info"), {
            "fields": [
                "checksum",
                "file_size",
            ],
            "classes": ["collapse"],
        }),
        (_("Timestamps"), {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]
    
    @display(description=_("Status"))
    def display_stable_status(self, obj):
        if obj.is_stable:
            return format_html(
                '<span style="color: #10b981;">✓ Stable</span>'
            )
        else:
            return format_html(
                '<span style="color: #f59e0b;">β Beta</span>'
            )
    
    @display(description=_("Size"))
    def display_file_size(self, obj):
        if obj.file_size:
            kb = obj.file_size / 1024
            return f"{kb:.1f} KB"
        return "-"
    
    @display(description=_("Adoption"))
    def display_adoption(self, obj):
        total = Device.objects.filter(status="active").count()
        on_version = Device.objects.filter(firmware_version=obj.version).count()
        if total > 0:
            percentage = (on_version / total) * 100
            return f"{on_version} ({percentage:.1f}%)"
        return "0 (0%)"
    
    @action(description=_("Mark as stable"))
    def mark_stable(self, request, queryset):
        count = queryset.update(is_stable=True)
        self.message_user(request, f"Marked {count} versions as stable")
    
    @action(description=_("Mark as beta"))
    def mark_beta(self, request, queryset):
        count = queryset.update(is_stable=False)
        self.message_user(request, f"Marked {count} versions as beta")
    
    actions = ["mark_stable", "mark_beta"]
