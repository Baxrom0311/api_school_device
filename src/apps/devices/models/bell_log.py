from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class BellLog(AbstractBaseModel):
    """Log entry for each bell ring event reported by a device."""

    class TriggerSource(models.TextChoices):
        SCHEDULE = "schedule", _("Schedule")
        MANUAL = "manual", _("Manual")
        EMERGENCY = "emergency", _("Emergency")
        MQTT = "mqtt", _("MQTT Command")

    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="bell_logs",
    )
    rang_at = models.DateTimeField(_("rang at"))
    duration_ms = models.PositiveIntegerField(_("duration (ms)"))
    trigger_source = models.CharField(
        _("trigger source"),
        max_length=20,
        choices=TriggerSource.choices,
        default=TriggerSource.SCHEDULE,
    )

    class Meta:
        db_table = "bell_logs"
        ordering = ["-rang_at"]
        indexes = [
            models.Index(fields=["device", "-rang_at"]),
            models.Index(fields=["rang_at"], name="bell_logs_rang_at_idx"),
        ]
        verbose_name = _("Bell Log")
        verbose_name_plural = _("Bell Logs")

    def __str__(self):
        return f"{self.device} rang at {self.rang_at}"
