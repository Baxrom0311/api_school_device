"""Rate limiting for emergency endpoints using Django cache (Redis)."""
import functools
import time

from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response


def emergency_rate_limit(cooldown_seconds: int = 30):
    """
    Decorator for DRF views: enforces cooldown between same emergency action.
    Uses cache key based on view class name.
    """
    def decorator(view_method):
        @functools.wraps(view_method)
        def wrapper(self, request, *args, **kwargs):
            key = f"emergency_cooldown:{self.__class__.__name__}"
            last_call = cache.get(key)
            if last_call is not None:
                elapsed = time.time() - last_call
                remaining = cooldown_seconds - elapsed
                if remaining > 0:
                    return Response(
                        {"error": "Rate limited", "retry_after": round(remaining, 1)},
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )
            cache.set(key, time.time(), timeout=cooldown_seconds)
            return view_method(self, request, *args, **kwargs)
        return wrapper
    return decorator
