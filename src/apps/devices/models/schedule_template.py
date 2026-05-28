from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class ScheduleTemplate(AbstractBaseModel):
    """Predefined schedule templates (e.g. 'Standard school', 'University')."""

    name = models.CharField(_("name"), max_length=100)
    description = models.TextField(_("description"), blank=True)
    times = models.JSONField(
        _("times"),
        help_text=_('List of times in 24h format, e.g. ["08:00", "08:45"]'),
    )
    is_default = models.BooleanField(_("default"), default=False)

    class Meta:
        db_table = "schedule_templates"
        ordering = ["name"]
        verbose_name = _("Schedule Template")
        verbose_name_plural = _("Schedule Templates")

    def __str__(self):
        return self.name
