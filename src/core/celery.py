import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.result_expires = 3600  # Expire task results after 1 hour

# Task queue routing: emergency tasks get priority queue
app.conf.task_routes = {
    "apps.devices.tasks.broadcast_emergency_command": {"queue": "emergency"},
    "apps.devices.tasks.notify_panic_alert": {"queue": "emergency"},
    "apps.devices.tasks.auto_clear_silence": {"queue": "emergency"},
    "apps.devices.tasks.process_ota_batch": {"queue": "ota"},
    "apps.devices.tasks.check_ota_completion": {"queue": "ota"},
}

app.conf.task_queue_max_priority = 10
app.conf.task_default_priority = 5

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
        "task": "apps.devices.tasks.cleanup_device_logs",
        "schedule": crontab(hour=3, minute=0),
        "kwargs": {"retention_days": 90},
    },
    # Sync holidays to devices daily at midnight
    "sync-holidays-to-devices": {
        "task": "apps.devices.tasks.sync_holidays_to_devices",
        "schedule": crontab(hour=0, minute=0),
    },
    # Sync iCal URLs to schedule templates every 6 hours
    "sync-ical-schedules": {
        "task": "apps.devices.tasks.sync_ical_schedules",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    # Cleanup old bell logs daily at 4 AM
    "cleanup-bell-logs": {
        "task": "apps.devices.tasks.cleanup_bell_logs",
        "schedule": crontab(hour=4, minute=0),
        "kwargs": {"retention_days": 30},
    },
    # Auto-clear silence at end of day (23:59) so next day resumes normal operation
    "auto-clear-silence": {
        "task": "apps.devices.tasks.auto_clear_silence",
        "schedule": crontab(hour=23, minute=59),
    },
    # Detect stale schedules (not synced in 7+ days) daily at 6 AM
    "detect-stale-schedules": {
        "task": "apps.devices.tasks.detect_stale_schedules",
        "schedule": crontab(hour=6, minute=0),
        "kwargs": {"stale_days": 7},
    },
    # Check consecutive RTC drift daily at 3:30 AM (after SNTP sync at 3:00)
    "check-rtc-consecutive-drift": {
        "task": "apps.devices.tasks.check_rtc_consecutive_drift",
        "schedule": crontab(hour=3, minute=30),
        "kwargs": {"drift_threshold_sec": 300},
    },
    # Check command ACK timeouts every 30 seconds
    "check-command-timeouts": {
        "task": "apps.devices.tasks.check_command_timeouts",
        "schedule": 30.0,
    },
}
