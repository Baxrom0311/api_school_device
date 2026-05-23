import os

from celery import Celery
from celery.schedules import crontab


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.result_expires = 3600  # Expire task results after 1 hour

# Connect Prometheus monitoring signals (optional dependency)
try:
    import core.celery_monitoring  # noqa: F401, E402
except ImportError:
    pass

# Celery Beat Schedule for IoT device monitoring
app.conf.beat_schedule = {
    # Sync pending schedules every 5 minutes
    "sync-pending-schedules": {
        "task": "apps.devices.tasks.sync_pending_schedules",
        "schedule": 300.0,  # Every 5 minutes
        "kwargs": {"max_devices": 100},
    },
    # Check OTA completion every 10 minutes (checks all active batches)
    "check-ota-timeouts": {
        "task": "apps.devices.tasks.check_ota_completion",
        "schedule": 600.0,  # Every 10 minutes
        "kwargs": {"timeout_minutes": 30},
    },
    # Daily report at 8 AM
    "daily-report": {
        "task": "apps.devices.tasks.generate_daily_report",
        "schedule": crontab(hour=8, minute=0),
    },
    # Detect stale devices every 6 hours
    "detect-stale-devices": {
        "task": "apps.devices.tasks.detect_stale_devices",
        "schedule": crontab(minute=0, hour="*/6"),
        "kwargs": {"threshold_hours": 24},
    },
    # Cleanup old device logs daily at 3 AM
    "cleanup-device-logs": {
        "task": "devices.cleanup_device_logs",
        "schedule": crontab(hour=3, minute=0),
        "kwargs": {"retention_days": 90},
    },
}
