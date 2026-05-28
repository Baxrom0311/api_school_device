from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class Holiday(AbstractBaseModel):
    """Holiday model — days when bells should not ring."""

    name = models.CharField(_("name"), max_length=100)
    date = models.DateField(_("date"))
    recurring = models.BooleanField(_("recurring yearly"), default=False)

    class Meta:
        db_table = "holidays"
        ordering = ["date"]
        unique_together = ["date", "name"]
        verbose_name = _("Holiday")
        verbose_name_plural = _("Holidays")

    def __str__(self):
        return f"{self.name} ({self.date})"
