"""
Celery task monitoring via Prometheus metrics.

Tracks task duration and failure rate using Celery signals.
Metrics are exposed via django-prometheus at /metrics.
"""
import time
import logging

from celery.signals import task_prerun, task_postrun, task_failure, task_retry
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

CELERY_TASK_DURATION = Histogram(
    "celery_task_duration_seconds",
    "Time spent executing Celery tasks",
    ["task_name"],
    buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 120, 300),
)

CELERY_TASK_TOTAL = Counter(
    "celery_task_total",
    "Total Celery tasks by name and state",
    ["task_name", "state"],
)

# Store start times keyed by task_id
_task_start_times: dict[str, float] = {}


@task_prerun.connect
def on_task_prerun(sender=None, task_id=None, **kwargs):
    _task_start_times[task_id] = time.time()


@task_postrun.connect
def on_task_postrun(sender=None, task_id=None, **kwargs):
    start = _task_start_times.pop(task_id, None)
    task_name = sender.name if sender else "unknown"
    if start is not None:
        CELERY_TASK_DURATION.labels(task_name=task_name).observe(time.time() - start)
    CELERY_TASK_TOTAL.labels(task_name=task_name, state="success").inc()


@task_failure.connect
def on_task_failure(sender=None, task_id=None, **kwargs):
    _task_start_times.pop(task_id, None)
    task_name = sender.name if sender else "unknown"
    CELERY_TASK_TOTAL.labels(task_name=task_name, state="failure").inc()


@task_retry.connect
def on_task_retry(sender=None, **kwargs):
    task_name = sender.name if sender else "unknown"
    CELERY_TASK_TOTAL.labels(task_name=task_name, state="retry").inc()
