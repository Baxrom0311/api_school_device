"""
OTABatch Model - Manages throttled OTA updates for groups of devices.

WHY this design:
1. OTA updates must be throttled to prevent server overload (100 devices/hour max)
2. Batch groups devices for controlled rollout
3. Status tracking per device within batch
4. Scheduling support for maintenance windows
5. Progress tracking for admin visibility
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class OTABatchStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    IN_PROGRESS = "in_progress", _("In Progress")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")
    CANCELLED = "cancelled", _("Cancelled")


class OTADeviceStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    NOTIFIED = "notified", _("Notified")  # MQTT sent
    DOWNLOADING = "downloading", _("Downloading")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    SKIPPED = "skipped", _("Skipped")


class OTABatch(AbstractBaseModel):
    """
    Batch OTA update job for controlled firmware rollout.

    Usage:
    1. Create batch with target firmware
    2. Add devices via OTABatchDevice
    3. Celery task processes batch respecting rate limits
    """

    name = models.CharField(
        max_length=255,
        verbose_name=_("Batch Name"),
        help_text=_("Descriptive name for this update batch"),
    )

    firmware = models.ForeignKey(
        "devices.FirmwareVersion",
        on_delete=models.PROTECT,
        related_name="ota_batches",
        verbose_name=_("Target Firmware"),
    )

    status = models.CharField(
        max_length=20,
        choices=OTABatchStatus.choices,
        default=OTABatchStatus.PENDING,
        verbose_name=_("Status"),
        db_index=True,
    )

    # Throttling configuration
    devices_per_hour = models.PositiveIntegerField(
        default=100,
        verbose_name=_("Devices Per Hour"),
        help_text=_("Maximum devices to update per hour (rate limiting)"),
    )

    # Scheduling
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Scheduled Start"),
        help_text=_("When to start the batch (null = immediate)"),
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Started At"),
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Completed At"),
    )

    # Progress tracking
    total_devices = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Total Devices"),
    )

    success_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Success Count"),
    )

    failure_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Failure Count"),
    )

    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ota_batches",
        verbose_name=_("Created By"),
    )

    class Meta:
        verbose_name = _("OTA Batch")
        verbose_name_plural = _("OTA Batches")
        ordering = ["-created_at"]
        db_table = "ota_batches"

    def __str__(self) -> str:
        return f"{self.name} - v{self.firmware.version} ({self.status})"

    @property
    def progress_percentage(self) -> float:
        """Calculate completion percentage"""
        if self.total_devices == 0:
            return 0.0
        processed = self.success_count + self.failure_count
        return round((processed / self.total_devices) * 100, 1)

    @property
    def pending_count(self) -> int:
        """Devices still waiting for update"""
        return self.total_devices - self.success_count - self.failure_count


class OTABatchDevice(AbstractBaseModel):
    """
    Individual device within an OTA batch.
    Tracks per-device update status.
    """

    batch = models.ForeignKey(
        OTABatch,
        on_delete=models.CASCADE,
        related_name="devices",
        verbose_name=_("Batch"),
    )

    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="ota_updates",
        verbose_name=_("Device"),
    )

    status = models.CharField(
        max_length=20,
        choices=OTADeviceStatus.choices,
        default=OTADeviceStatus.PENDING,
        verbose_name=_("Status"),
        db_index=True,
    )

    notified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Notified At"),
        help_text=_("When OTA command was sent via MQTT"),
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Completed At"),
    )

    previous_version = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Previous Version"),
    )

    error_message = models.TextField(
        blank=True,
        verbose_name=_("Error Message"),
    )

    retry_count = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("Retry Count"),
    )

    class Meta:
        verbose_name = _("OTA Batch Device")
        verbose_name_plural = _("OTA Batch Devices")
        db_table = "ota_batch_devices"
        unique_together = [["batch", "device"]]
        indexes = [
            models.Index(fields=["batch", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.device.device_id} in {self.batch.name} ({self.status})"
