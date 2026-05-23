"""
EMQX HTTP Auth Endpoint - Verifies device MQTT credentials.

EMQX HTTP auth plugin calls this endpoint when a device connects.
See: https://www.emqx.io/docs/en/latest/access-control/authn/http.html

EMQX config:
  authentication:
    - mechanism: password_based
      backend: http
      method: post
      url: "http://django:8000/api/v1/mqtt/auth/"
      headers:
        X-MQTT-Auth-Secret: "${MQTT_AUTH_SECRET}"
      body:
        username: "${username}"
        password: "${password}"
"""
import hmac
import logging
import os

from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from django.contrib.auth.hashers import check_password

from apps.devices.models import Device

logger = logging.getLogger(__name__)

MQTT_AUTH_SECRET = os.getenv("MQTT_AUTH_SECRET", "")
MQTT_AUTH_CACHE_TTL = 300  # 5 minutes


def _verify_shared_secret(request) -> bool:
    """Verify the shared secret header from EMQX. Fail-closed when not configured."""
    if not MQTT_AUTH_SECRET:
        logger.warning("MQTT_AUTH_SECRET not configured — denying all MQTT auth requests")
        return False
    header = request.META.get("HTTP_X_MQTT_AUTH_SECRET", "")
    return hmac.compare_digest(header, MQTT_AUTH_SECRET)


class MQTTAuthView(APIView):
    """Verify MQTT credentials for EMQX HTTP auth plugin."""

    permission_classes = [AllowAny]
    authentication_classes = []  # No JWT needed - EMQX calls this
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        if not _verify_shared_secret(request):
            return Response(status=status.HTTP_403_FORBIDDEN)

        username = request.data.get("username", "")
        password = request.data.get("password", "")

        if not username or not password:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # Check cache first to avoid DB hit on frequent reconnects
        cache_key = f"mqtt_auth:{username}"
        cached = cache.get(cache_key)
        if cached is not None:
            if check_password(password, cached["mqtt_password"]):
                return Response({"result": "allow"})
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        try:
            device = Device.objects.get(mqtt_username=username)
        except Device.DoesNotExist:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        if not check_password(password, device.mqtt_password):
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        # Only allow registered devices to connect
        if device.registration_status != "registered":
            return Response(status=status.HTTP_403_FORBIDDEN)

        # Deny inactive devices
        if getattr(device, "status", "active") == "inactive":
            return Response(status=status.HTTP_403_FORBIDDEN)

        # Cache successful auth to reduce DB load
        cache.set(cache_key, {
            "mqtt_password": device.mqtt_password,
            "registration_status": device.registration_status,
            "status": getattr(device, "status", "active"),
        }, MQTT_AUTH_CACHE_TTL)

        return Response({"result": "allow"})


class MQTTACLView(APIView):
    """Verify MQTT topic ACL for EMQX HTTP auth plugin.

    Ensures devices can only pub/sub to their own topics.
    Uses caching to avoid DB hits on high-frequency pub/sub checks.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        if not _verify_shared_secret(request):
            return Response(status=status.HTTP_403_FORBIDDEN)

        username = request.data.get("username", "")
        topic = request.data.get("topic", "")

        if not username or not topic:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # Check cache for device_id mapping to avoid DB lookup
        cache_key = f"mqtt_acl:{username}"
        device_id = cache.get(cache_key)

        if device_id is None:
            try:
                device = Device.objects.only("device_id").get(mqtt_username=username)
            except Device.DoesNotExist:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
            device_id = device.device_id
            cache.set(cache_key, device_id, MQTT_AUTH_CACHE_TTL)

        # Device can only access its own topics: devices/{device_id}/*
        allowed_prefix = f"devices/{device_id}/"
        if not topic.startswith(allowed_prefix):
            return Response(status=status.HTTP_403_FORBIDDEN)

        return Response({"result": "allow"})
