"""
Regression tests for the MQTT broker reachability probe used by /health/.

Background: the previous implementation called
``mqtt_publisher.is_connected()`` directly. Because the publisher uses
lazy connect, a freshly-started process would always report
``"disconnected"`` even when the broker is healthy, so the health check
flapped on every deploy. The new helper falls back to a TCP probe.

These tests pin three behaviours:
  1. When the in-process publisher reports connected, the helper short-
     circuits and returns ``("ok", None)`` without touching the network.
  2. When the publisher reports not-connected, the helper does a TCP
     probe and returns ``("reachable", None)`` on success.
  3. Errors never leak the broker host or port.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.shared.views import health as health_module


def test_publisher_connected_short_circuits():
    """If the publisher is already connected, no TCP work happens."""
    with (
        patch.object(health_module.mqtt_publisher, "is_connected", return_value=True),
        patch("apps.shared.views.health.socket.socket") as mock_sock,
    ):
        status, err = health_module._check_mqtt_broker_reachable()
    assert status == "ok"
    assert err is None
    mock_sock.assert_not_called()


def test_tcp_probe_used_when_publisher_disconnected(monkeypatch):
    """Fallback to TCP probe when publisher is not connected."""
    monkeypatch.setenv("MQTT_BROKER_HOST", "broker.example")
    monkeypatch.setenv("MQTT_BROKER_PORT", "1883")

    class _OkSock:
        def settimeout(self, _):
            pass

        def connect(self, _addr):
            return None

        def close(self):
            pass

    with (
        patch.object(health_module.mqtt_publisher, "is_connected", return_value=False),
        patch("apps.shared.views.health.socket.socket", return_value=_OkSock()),
    ):
        status, err = health_module._check_mqtt_broker_reachable()

    assert status == "reachable"
    assert err is None


def test_tcp_probe_failure_does_not_leak_host(monkeypatch):
    """Connection refused → status 'unreachable', error string contains
    only the OSError class name, never the host or port."""
    sensitive_host = "secret-broker.internal"
    sensitive_port = "1883"
    monkeypatch.setenv("MQTT_BROKER_HOST", sensitive_host)
    monkeypatch.setenv("MQTT_BROKER_PORT", sensitive_port)

    class _BadSock:
        def settimeout(self, _):
            pass

        def connect(self, _addr):
            raise ConnectionRefusedError("refused")

        def close(self):
            pass

    with (
        patch.object(health_module.mqtt_publisher, "is_connected", return_value=False),
        patch("apps.shared.views.health.socket.socket", return_value=_BadSock()),
    ):
        status, err = health_module._check_mqtt_broker_reachable()

    assert status == "unreachable"
    assert err == "ConnectionRefusedError"
    assert sensitive_host not in (err or "")
    assert sensitive_port not in (err or "")


def test_unconfigured_when_host_missing(monkeypatch):
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    with patch.object(health_module.mqtt_publisher, "is_connected", return_value=False):
        status, err = health_module._check_mqtt_broker_reachable()
    assert status == "unconfigured"
    assert err is None


def test_invalid_port_reported_as_misconfigured(monkeypatch):
    monkeypatch.setenv("MQTT_BROKER_HOST", "broker.example")
    monkeypatch.setenv("MQTT_BROKER_PORT", "not-a-number")
    with patch.object(health_module.mqtt_publisher, "is_connected", return_value=False):
        status, err = health_module._check_mqtt_broker_reachable()
    assert status == "misconfigured"
    assert err == "invalid MQTT_BROKER_PORT"


@pytest.mark.django_db
def test_health_endpoint_uses_tcp_probe_path(api_client, monkeypatch):
    """End-to-end: with publisher disconnected but TCP reachable, the
    /health/ endpoint must report mqtt_broker='reachable' and not
    'disconnected' (the legacy bug)."""
    monkeypatch.setenv("MQTT_BROKER_HOST", "broker.example")
    monkeypatch.setenv("MQTT_BROKER_PORT", "1883")

    class _OkSock:
        def settimeout(self, _):
            pass

        def connect(self, _addr):
            return None

        def close(self):
            pass

    with (
        patch.object(health_module.mqtt_publisher, "is_connected", return_value=False),
        patch("apps.shared.views.health.socket.socket", return_value=_OkSock()),
        patch("apps.shared.views.health.cache") as mock_cache,
    ):
        mock_cache.set.return_value = None
        mock_cache.get.side_effect = lambda key, *a: "1" if key == "_health" else {"x": 1}
        response = api_client.get("/api/v1/health/")

    assert response.data["checks"]["mqtt_broker"] == "reachable"
    assert "disconnected" not in str(response.data["checks"])
