from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class ScheduleHistory(AbstractBaseModel):
    """Archived schedule snapshot — created automatically when a schedule is updated."""

    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="schedule_history",
        verbose_name=_("Device"),
    )
    times = models.JSONField(verbose_name=_("Ring Times"))
    days_mask = models.PositiveSmallIntegerField(verbose_name=_("Days Mask"))
    bell_duration = models.PositiveIntegerField(verbose_name=_("Bell Duration (ms)"))
    version = models.PositiveIntegerField(verbose_name=_("Version"))
    changed_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name=_("Changed By"),
    )

    class Meta:
        db_table = "schedule_history"
        ordering = ["-created_at"]
        verbose_name = _("Schedule History")
        verbose_name_plural = _("Schedule History")

    def __str__(self):
        times_count = len(self.times) if isinstance(self.times, list) else 0
        return f"v{self.version} — {times_count} times ({self.created_at:%Y-%m-%d %H:%M})"
