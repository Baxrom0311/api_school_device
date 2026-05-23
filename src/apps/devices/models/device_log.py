from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class LogLevel(models.TextChoices):
    DEBUG = "debug", _("Debug")
    INFO = "info", _("Info")
    WARNING = "warning", _("Warning")
    ERROR = "error", _("Error")
    CRITICAL = "critical", _("Critical")


class LogSource(models.TextChoices):
    DEVICE = "device", _("Device")
    SERVER = "server", _("Server")
    OTA = "ota", _("OTA")
    MQTT = "mqtt", _("MQTT")


class DeviceLog(AbstractBaseModel):
    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="logs",
    )
    level = models.CharField(max_length=10, choices=LogLevel.choices)
    source = models.CharField(max_length=10, choices=LogSource.choices)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Device Log")
        verbose_name_plural = _("Device Logs")
        ordering = ["-created_at"]
        db_table = "device_logs"
        indexes = [
            models.Index(fields=["device", "-created_at"], name="devicelog_device_created"),
            models.Index(fields=["level", "-created_at"], name="devicelog_level_created"),
        ]

    def __str__(self) -> str:
        return f"[{self.level}] {self.device.device_id}: {self.message[:50]}"
