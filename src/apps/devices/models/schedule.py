"""
Schedule Model - Stores bell ring schedules for each device.

WHY this design:
1. OneToOne with Device - each device has exactly one schedule
2. times stored as JSONField for flexibility (variable number of times per day)
3. is_active allows temporarily disabling schedule without deletion
4. timezone support for devices in different zones (future-proofing)
5. synced_at tracks when schedule was last pushed to device
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinLengthValidator

from apps.shared.models.base import AbstractBaseModel


class Schedule(AbstractBaseModel):
    """
    Bell schedule for a device.
    
    JSON format for times: ["08:30", "09:15", "10:00", ...]
    Times are in 24-hour format, HH:MM
    """
    
    device = models.OneToOneField(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="schedule",
        verbose_name=_("Device"),
    )
    
    times = models.JSONField(
        default=list,
        verbose_name=_("Ring Times"),
        help_text=_('List of times in 24h format, e.g. ["08:30", "09:15"]'),
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Is Active"),
        help_text=_("Whether this schedule is currently active"),
    )
    
    timezone = models.CharField(
        max_length=50,
        default="Asia/Tashkent",
        verbose_name=_("Timezone"),
        help_text=_("Device timezone for schedule interpretation"),
    )
    
    # Sync tracking
    synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Synced"),
        help_text=_("When schedule was last pushed to device via MQTT"),
    )
    sync_pending = models.BooleanField(
        default=True,
        verbose_name=_("Sync Pending"),
        help_text=_("Whether schedule needs to be pushed to device"),
    )
    
    class Meta:
        verbose_name = _("Schedule")
        verbose_name_plural = _("Schedules")
        db_table = "device_schedules"

    def __str__(self) -> str:
        times_count = len(self.times) if isinstance(self.times, list) else 0
        return f"Schedule for {self.device.device_id} ({times_count} times)"
    
    def save(self, *args, **kwargs):
        # Mark as needing sync whenever times change
        if self.pk:
            old = Schedule.objects.filter(pk=self.pk).values("times").first()
            if old and old["times"] != self.times:
                self.sync_pending = True
        super().save(*args, **kwargs)
    
    @property
    def times_count(self) -> int:
        """Number of scheduled ring times"""
        return len(self.times) if isinstance(self.times, list) else 0
    
    def validate_times(self) -> list[str]:
        """Validate and return list of errors"""
        import re
        errors = []
        time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')
        
        if not isinstance(self.times, list):
            errors.append("Times must be a list")
            return errors
            
        for i, time in enumerate(self.times):
            if not isinstance(time, str):
                errors.append(f"Time at index {i} must be a string")
            elif not time_pattern.match(time):
                errors.append(f"Invalid time format at index {i}: {time}")
        
        return errors
