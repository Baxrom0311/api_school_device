"""
Regression tests: every task in the Celery beat schedule must resolve to a
real registered Celery task. This guards against mismatched task names like
the legacy "devices.cleanup_device_logs" vs the autoderived
"apps.devices.tasks.cleanup_device_logs".
"""

import pytest

from core.celery import app


def _registered_task_names() -> set[str]:
    """Force task autodiscovery so app.tasks is populated, then return names."""
    # Importing the tasks module is what registers them with the @shared_task
    # decorator; autodiscover_tasks() in core/celery.py runs on app load but
    # is lazy in some Celery versions, so we explicitly import here.
    import apps.devices.tasks  # noqa: F401

    return set(app.tasks.keys())


def test_every_beat_task_is_registered():
    registered = _registered_task_names()
    for entry_name, entry in app.conf.beat_schedule.items():
        task_name = entry["task"]
        assert task_name in registered, (
            f"Beat entry {entry_name!r} references task {task_name!r} which "
            f"is not registered. Registered task names: {sorted(registered)}"
        )


def test_all_device_tasks_use_canonical_namespace():
    """
    All tasks in apps/devices/tasks.py must register under the
    'apps.devices.tasks.X' namespace. This catches any future drift back to
    short-form names like 'devices.cleanup_device_logs'.
    """
    registered = _registered_task_names()
    device_task_names = [n for n in registered if n.startswith("apps.devices.tasks.")]
    assert device_task_names, "expected at least one apps.devices.tasks.* task"

    legacy_names = [n for n in registered if n.startswith("devices.")]
    assert not legacy_names, (
        f"Legacy short-form Celery task names detected: {legacy_names}. "
        "All device tasks must use the auto-derived 'apps.devices.tasks.*' "
        "namespace; remove explicit name= kwargs from @shared_task."
    )


@pytest.mark.parametrize(
    "expected_task",
    [
        "apps.devices.tasks.cleanup_device_logs",
        "apps.devices.tasks.cleanup_bell_logs",
        "apps.devices.tasks.check_command_timeouts",
        "apps.devices.tasks.sync_pending_schedules",
        "apps.devices.tasks.check_ota_completion",
        "apps.devices.tasks.detect_stale_devices",
        "apps.devices.tasks.sync_holidays_to_devices",
        "apps.devices.tasks.auto_clear_silence",
    ],
)
def test_beat_schedule_includes_canonical_names(expected_task):
    """Specific check that the beat schedule references the canonical names."""
    scheduled_tasks = {entry["task"] for entry in app.conf.beat_schedule.values()}
    assert expected_task in scheduled_tasks, (
        f"Expected {expected_task!r} in beat_schedule but found: {sorted(scheduled_tasks)}"
    )
