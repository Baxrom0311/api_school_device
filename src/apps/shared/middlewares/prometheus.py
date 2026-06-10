import re
import time

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin
from prometheus_client import Counter, Gauge, Histogram

REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request duration by path", ["path"])
REQUEST_COUNT = Counter("http_request_total", "Total HTTP requests by path and status", ["path", "status"])

# IoT-specific metrics
MQTT_PUBLISH_TOTAL = Counter("mqtt_publish_total", "MQTT publish attempts", ["result"])
OTA_BATCH_PROGRESS = Gauge("ota_batch_in_progress", "Number of OTA batches currently in progress")
DEVICE_ONLINE_COUNT = Gauge("device_online_count", "Number of devices currently online")

# Patterns to normalize in URL paths
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_ID_RE = re.compile(r"/\d+(?=/|$)")


def _normalize_path(path: str) -> str:
    """Strip UUIDs and numeric IDs from path to prevent metric cardinality explosion."""
    path = _UUID_RE.sub("{id}", path)
    path = _ID_RE.sub("/{id}", path)
    return path


class MetricsMiddleware(MiddlewareMixin):
    def process_request(self, request: HttpRequest) -> HttpResponse | None:
        request.META["metrics_start_time"] = time.time()
        return None

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        start_time = request.META.get("metrics_start_time")
        if start_time is not None:
            duration = time.time() - start_time
            path = _normalize_path(request.path)
            REQUEST_LATENCY.labels(path=path).observe(duration)
            REQUEST_COUNT.labels(path=path, status=response.status_code).inc()
        return response
