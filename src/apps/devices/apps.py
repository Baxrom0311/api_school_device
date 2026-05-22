from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DevicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.devices"
    verbose_name = _("IoT Devices")

    def ready(self):
        # Import signals when app is ready
        try:
            import apps.devices.signals  # noqa: F401
        except ImportError:
            pass
