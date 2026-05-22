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
      body:
        username: "${username}"
        password: "${password}"
"""
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from django.contrib.auth.hashers import check_password

from apps.devices.models import Device


class MQTTAuthView(APIView):
    """Verify MQTT credentials for EMQX HTTP auth plugin."""

    permission_classes = [AllowAny]
    authentication_classes = []  # No JWT needed - EMQX calls this
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        username = request.data.get("username", "")
        password = request.data.get("password", "")

        if not username or not password:
            return Response(status=status.HTTP_400_BAD_REQUEST)

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

        return Response({"result": "allow"})


class MQTTACLView(APIView):
    """Verify MQTT topic ACL for EMQX HTTP auth plugin.

    Ensures devices can only pub/sub to their own topics.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        username = request.data.get("username", "")
        topic = request.data.get("topic", "")

        if not username or not topic:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            device = Device.objects.get(mqtt_username=username)
        except Device.DoesNotExist:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        # Device can only access its own topics: devices/{device_id}/*
        allowed_prefix = f"devices/{device.device_id}/"
        if not topic.startswith(allowed_prefix):
            return Response(status=status.HTTP_403_FORBIDDEN)

        return Response({"result": "allow"})
