"""
Request-ID middleware.

Generates a UUID per request and attaches it to the response header
and logging context for traceability.
"""
import uuid
import logging
import threading

_local = threading.local()


def get_request_id() -> str:
    return getattr(_local, "request_id", "-")


class RequestIDFilter(logging.Filter):
    def filter(self, record):
        record.request_id = get_request_id()
        return True


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        _local.request_id = request_id
        request.request_id = request_id

        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response
