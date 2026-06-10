from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class HolidayRange(AbstractBaseModel):
    """Holiday date range — periods when bells should not ring (e.g. summer/winter break)."""

    name = models.CharField(_("name"), max_length=100)
    from_month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    from_day = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(31)])
    to_month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    to_day = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(31)])
    device = models.ForeignKey(
        "devices.Device",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="holiday_ranges",
        help_text=_("Null = global (applies to all devices)"),
    )

    class Meta:
        db_table = "holiday_ranges"
        verbose_name = _("Holiday Range")
        verbose_name_plural = _("Holiday Ranges")

    def __str__(self):
        return f"{self.name} ({self.from_month}/{self.from_day} - {self.to_month}/{self.to_day})"
