"""
OTA Batch Admin
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

from apps.devices.models import OTABatch, OTABatchDevice
from apps.devices.models.ota_batch import OTABatchStatus


class OTABatchDeviceInline(TabularInline):
    """Inline view of devices in batch"""

    model = OTABatchDevice
    extra = 0
    fields = [
        "device",
        "status",
        "previous_version",
        "notified_at",
        "completed_at",
        "error_message",
    ]
    readonly_fields = [
        "status",
        "previous_version",
        "notified_at",
        "completed_at",
        "error_message",
    ]
    can_delete = False
    max_num = 0  # Prevent adding new entries

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OTABatch)
class OTABatchAdmin(ModelAdmin):
    """OTA Batch admin"""

    list_display = [
        "name",
        "firmware",
        "display_status",
        "display_progress",
        "devices_per_hour",
        "created_by",
        "created_at",
    ]
    list_filter = [
        "status",
        "firmware",
        "created_at",
    ]
    search_fields = [
        "name",
        "firmware__version",
    ]
    readonly_fields = [
        "status",
        "started_at",
        "completed_at",
        "total_devices",
        "success_count",
        "failure_count",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (
            _("Batch Info"),
            {
                "fields": [
                    "name",
                    "firmware",
                    "status",
                ],
            },
        ),
        (
            _("Configuration"),
            {
                "fields": [
                    "devices_per_hour",
                    "scheduled_at",
                ],
            },
        ),
        (
            _("Progress"),
            {
                "fields": [
                    "total_devices",
                    "success_count",
                    "failure_count",
                    "started_at",
                    "completed_at",
                ],
            },
        ),
        (
            _("Metadata"),
            {
                "fields": [
                    "created_by",
                    "created_at",
                    "updated_at",
                ],
                "classes": ["collapse"],
            },
        ),
    ]
    inlines = [OTABatchDeviceInline]

    @display(
        description=_("Status"),
        label={
            "pending": "info",
            "in_progress": "warning",
            "completed": "success",
            "failed": "danger",
            "cancelled": "danger",
        },
    )
    def display_status(self, obj):
        return obj.status

    @display(description=_("Progress"))
    def display_progress(self, obj):
        if obj.total_devices == 0:
            return "-"

        processed = obj.success_count + obj.failure_count
        percentage = (processed / obj.total_devices) * 100

        return format_html(
            '<div style="width:100px; background:#e5e7eb; border-radius:4px;">'
            '<div style="width:{}%; background:#10b981; height:8px; border-radius:4px;"></div>'
            "</div>"
            '<span style="font-size:12px;">{}/{} ({:.1f}%)</span>',
            min(percentage, 100),
            processed,
            obj.total_devices,
            percentage,
        )

    @action(description=_("Start selected batches"))
    def start_batches(self, request, queryset):
        from django.utils import timezone

        from apps.devices.tasks import process_ota_batch

        count = 0
        for batch in queryset.filter(status=OTABatchStatus.PENDING):
            batch.status = OTABatchStatus.IN_PROGRESS
            batch.started_at = timezone.now()
            batch.save(update_fields=["status", "started_at"])
            process_ota_batch.delay(batch.id)
            count += 1

        self.message_user(request, f"Started {count} batches")

    @action(description=_("Cancel selected batches"))
    def cancel_batches(self, request, queryset):
        from django.utils import timezone

        count = queryset.filter(status__in=[OTABatchStatus.PENDING, OTABatchStatus.IN_PROGRESS]).update(
            status=OTABatchStatus.CANCELLED, completed_at=timezone.now()
        )

        self.message_user(request, f"Cancelled {count} batches")

    actions = ["start_batches", "cancel_batches"]


@admin.register(OTABatchDevice)
class OTABatchDeviceAdmin(ModelAdmin):
    """OTA Batch Device admin (for detailed view)"""

    list_display = [
        "device",
        "batch",
        "status",
        "previous_version",
        "notified_at",
        "completed_at",
    ]
    list_filter = [
        "status",
        "batch",
    ]
    search_fields = [
        "device__device_id",
        "batch__name",
    ]
    readonly_fields = [
        "batch",
        "device",
        "status",
        "previous_version",
        "notified_at",
        "completed_at",
        "error_message",
        "retry_count",
    ]
