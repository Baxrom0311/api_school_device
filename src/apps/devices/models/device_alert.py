from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class DeviceAlert(AbstractBaseModel):
    """Alert raised by device (panic button) or admin (emergency ring, lockdown)."""

    class AlertType(models.TextChoices):
        PANIC = "panic", _("Panic")
        LOCKDOWN = "lockdown", _("Lockdown")
        EMERGENCY_RING = "emergency_ring", _("Emergency Ring")
        OFFLINE = "offline", _("Device Offline")
        RTC_DRIFT = "rtc_drift", _("RTC Drift")
        RTC_BATTERY_DEAD = "rtc_battery_dead", _("RTC Battery Dead")
        SCHEDULE_STALE = "schedule_stale", _("Schedule Stale")

    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
    )
    alert_type = models.CharField(_("alert type"), max_length=20, choices=AlertType.choices)
    resolved = models.BooleanField(_("resolved"), default=False)
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)

    class Meta:
        db_table = "device_alerts"
        ordering = ["-created_at"]
        verbose_name = _("Device Alert")
        verbose_name_plural = _("Device Alerts")
        constraints = [
            models.UniqueConstraint(
                fields=["device", "alert_type"],
                condition=models.Q(resolved=False),
                name="unique_unresolved_alert_per_device",
            ),
        ]

    def __str__(self):
        return f"{self.alert_type} - {self.created_at}"
