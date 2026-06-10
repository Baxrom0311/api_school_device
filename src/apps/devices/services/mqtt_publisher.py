"""
MQTT Publisher Service - Sends commands to ESP8266 devices.

WHY this design:
1. Singleton pattern for connection reuse - MQTT connections are expensive
2. Thread-safe publishing with connection management
3. QoS 1 for important commands (schedule, OTA) to ensure delivery
4. QoS 0 for ring commands (fire-and-forget, real-time)
5. Automatic reconnection handling
6. Structured command helpers for type safety
7. Circuit breaker prevents hammering a down broker
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, ClassVar

import paho.mqtt.client as mqtt
from paho.mqtt.client import ConnectFlags, DisconnectFlags
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

logger = logging.getLogger(__name__)

try:
    from apps.shared.middlewares.prometheus import MQTT_PUBLISH_TOTAL
except Exception:
    MQTT_PUBLISH_TOTAL = None  # type: ignore[assignment]


# ============ Circuit Breaker ============


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open and calls are rejected."""

    pass


class CircuitBreaker:
    """
    Simple circuit breaker to avoid hammering a down MQTT broker.

    States: CLOSED (normal) -> OPEN (failing) -> HALF_OPEN (testing recovery)
    """

    CLOSED: ClassVar[str] = "closed"
    OPEN: ClassVar[str] = "open"
    HALF_OPEN: ClassVar[str] = "half_open"

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self._state: str = self.CLOSED
        self._failure_count: int = 0
        self._failure_threshold: int = failure_threshold
        self._recovery_timeout: float = recovery_timeout
        self._last_failure_time: float = 0.0
        self._lock: threading.Lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN:
                if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                    self._state = self.HALF_OPEN
            return self._state

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._failure_threshold:
                self._state = self.OPEN
                logger.warning(
                    "Circuit breaker OPEN after %s failures. Will retry in %ss.",
                    self._failure_count,
                    self._recovery_timeout,
                )

    def allow_request(self) -> bool:
        state = self.state
        return state in (self.CLOSED, self.HALF_OPEN)


@dataclass
class MQTTConfig:
    """MQTT broker configuration"""

    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str = "django-publisher"
    keepalive: int = 60
    use_tls: bool = False

    @classmethod
    def from_env(cls) -> MQTTConfig:
        """Load configuration from environment variables"""
        return cls(
            host=os.getenv("MQTT_BROKER_HOST", "localhost"),
            port=int(os.getenv("MQTT_BROKER_PORT", "1883")),
            username=os.getenv("MQTT_USERNAME"),
            password=os.getenv("MQTT_PASSWORD"),
            client_id=os.getenv("MQTT_CLIENT_ID", "django-publisher"),
            keepalive=int(os.getenv("MQTT_KEEPALIVE", "60")),
            use_tls=os.getenv("MQTT_USE_TLS", "false").lower() == "true",
        )


# Heartbeat cache key written on every successful publish / connect.
# Health checks read this to determine if the publisher is alive.
MQTT_PUBLISHER_ALIVE_CACHE_KEY: str = "mqtt_publisher:alive"
MQTT_PUBLISHER_ALIVE_TTL_SECONDS: int = 120


class MQTTPublisher:
    """
    Thread-safe MQTT publisher for sending commands to devices.

    Usage:
        from apps.devices.services import mqtt_publisher

        mqtt_publisher.send_schedule("device_001", ["08:30", "09:15"])
        mqtt_publisher.ring("device_001", duration=5)
        mqtt_publisher.send_ota("device_001", "http://server/firmware/v1.2.3.bin")
    """

    _instance: ClassVar[MQTTPublisher | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    # Instance attributes (declared at class level so mypy can see them).
    _initialized: bool
    _client: mqtt.Client | None
    _connected: bool
    _connect_lock: threading.Lock
    _circuit_breaker: CircuitBreaker
    config: MQTTConfig

    def __new__(cls, config: MQTTConfig | None = None) -> MQTTPublisher:
        """Singleton pattern - reuse connection across requests"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    instance._client = None
                    instance._connected = False
                    instance._connect_lock = threading.Lock()
                    instance._circuit_breaker = CircuitBreaker(
                        failure_threshold=int(os.getenv("MQTT_CB_FAILURE_THRESHOLD", "5")),
                        recovery_timeout=float(os.getenv("MQTT_CB_RECOVERY_TIMEOUT", "60")),
                    )
                    instance.config = config or MQTTConfig.from_env()
                    instance._initialized = True
                    cls._instance = instance
        return cls._instance

    def __init__(self, config: MQTTConfig | None = None) -> None:
        # Singleton initialisation happens in __new__ to keep state across reuses.
        return None

    @staticmethod
    def _mark_alive() -> None:
        """Write the publisher heartbeat to the cache. Used by health checks."""
        try:
            from django.core.cache import cache

            cache.set(MQTT_PUBLISHER_ALIVE_CACHE_KEY, "1", timeout=MQTT_PUBLISHER_ALIVE_TTL_SECONDS)
        except Exception:
            # Cache is best-effort; never break publishing because of it.
            logger.debug("Failed to update MQTT publisher liveness cache", exc_info=True)

    def _get_client(self) -> mqtt.Client:
        """Get or create MQTT client with lazy connection"""
        with self._connect_lock:
            if self._client is None or not self._connected:
                self._connect()
            assert self._client is not None  # noqa: S101 - narrow type for mypy
            return self._client

    def _connect(self) -> None:
        """Establish connection to MQTT broker"""
        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.config.client_id,
                protocol=mqtt.MQTTv311,
            )

            # Set callbacks
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect

            # Authentication
            if self.config.username and self.config.password:
                self._client.username_pw_set(self.config.username, self.config.password)

            # TLS
            if self.config.use_tls:
                self._client.tls_set()

            # Connect
            self._client.connect(self.config.host, self.config.port, self.config.keepalive)

            # Start background loop for handling callbacks
            self._client.loop_start()

            logger.info(
                "MQTT Publisher connecting to %s:%s",
                self.config.host,
                self.config.port,
            )

        except Exception as e:
            # Avoid leaking the broker host/port into propagated error chains.
            logger.error("MQTT connection failed: %s", e)
            self._connected = False
            raise

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: ConnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        """Callback when connected to broker"""
        if getattr(reason_code, "value", reason_code) == 0:
            self._connected = True
            self._mark_alive()
            logger.info("MQTT Publisher connected successfully")
        else:
            self._connected = False
            logger.error("MQTT connection failed with code: %s", reason_code)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: DisconnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        """Callback when disconnected from broker"""
        self._connected = False
        if getattr(reason_code, "value", reason_code) != 0:
            logger.warning("MQTT unexpected disconnect: %s", reason_code)

    def is_connected(self) -> bool:
        """Check if MQTT client is currently connected"""
        return self._connected

    def publish(self, topic: str, payload: dict[str, Any], qos: int = 1, retain: bool = False) -> bool:
        """
        Publish a message to MQTT broker.

        Args:
            topic: MQTT topic
            payload: Dictionary to be JSON encoded
            qos: Quality of Service (0, 1, or 2)
            retain: Retain message on broker

        Returns:
            True if published successfully

        Raises nothing - returns False on failure (circuit breaker included).
        """
        if not self._circuit_breaker.allow_request():
            logger.warning("Circuit breaker OPEN, dropping publish to %s", topic)
            if MQTT_PUBLISH_TOTAL:
                MQTT_PUBLISH_TOTAL.labels(result="circuit_open").inc()
            return False

        try:
            client = self._get_client()
            message = json.dumps(payload)

            result = client.publish(topic, message, qos=qos, retain=retain)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug("Published to %s: %s", topic, message)
                self._circuit_breaker.record_success()
                self._mark_alive()
                if MQTT_PUBLISH_TOTAL:
                    MQTT_PUBLISH_TOTAL.labels(result="success").inc()
                return True
            else:
                logger.error("Publish failed to %s: rc=%s", topic, result.rc)
                self._circuit_breaker.record_failure()
                if MQTT_PUBLISH_TOTAL:
                    MQTT_PUBLISH_TOTAL.labels(result="failure").inc()
                return False

        except Exception as e:
            # Do not include broker host/port in the error string.
            logger.error("Publish error: %s", e)
            self._circuit_breaker.record_failure()
            if MQTT_PUBLISH_TOTAL:
                MQTT_PUBLISH_TOTAL.labels(result="failure").inc()
            return False

    def send_to_device(self, device_id: str, payload: dict[str, Any], qos: int = 1) -> bool:
        """
        Send command to specific device.

        Topic format: devices/{device_id}/command
        """
        topic = f"devices/{device_id}/command"
        return self.publish(topic, payload, qos=qos)

    # ============ Command Helpers ============

    def _create_command_log(self, device_id: str, command_type: str, payload: dict[str, Any]) -> str | None:
        """Create CommandLog and return msg_id string. Returns None if device not found."""
        try:
            import uuid

            from apps.devices.models import Device
            from apps.devices.models.command_log import CommandLog

            device = Device.objects.get(device_id=device_id)
            msg_id = uuid.uuid4()
            CommandLog.objects.create(
                device=device,
                msg_id=msg_id,
                command_type=command_type,
                payload=payload,
            )
            return str(msg_id)
        except Exception as e:
            logger.warning("Failed to create CommandLog for %s: %s", device_id, e)
            return None

    def send_schedule(
        self,
        device_id: str,
        times: list[str],
        version: int = 0,
        days_mask: int = 0x1F,
        bell_duration: int = 3000,
    ) -> str | bool | None:
        """
        Push schedule to device via schedule topic.

        Returns msg_id string on success, None on failure.
        """
        entries: list[dict[str, int]] = []
        for t in times:
            parts = t.split(":")
            if len(parts) == 2:
                entries.append(
                    {
                        "hour": int(parts[0]),
                        "minute": int(parts[1]),
                        "duration": bell_duration,
                        "days": days_mask,
                    }
                )

        topic = f"devices/{device_id}/schedule"
        payload: dict[str, Any] = {"version": version, "entries": entries}

        msg_id = self._create_command_log(device_id, "schedule_sync", payload)
        if msg_id:
            payload["msg_id"] = msg_id

        success = self.publish(topic, payload, qos=1, retain=True)

        if success:
            logger.info(
                "Schedule sent to %s: %s entries, msg_id=%s",
                device_id,
                len(entries),
                msg_id,
            )
            return msg_id or True
        return None

    def ring(self, device_id: str, duration: int = 5) -> str | bool | None:
        """
        Trigger immediate ring on device.

        Returns msg_id string on success, None on failure.
        """
        payload: dict[str, Any] = {"command": "ring", "duration": duration}

        msg_id = self._create_command_log(device_id, "ring", payload)
        if msg_id:
            payload["msg_id"] = msg_id

        success = self.send_to_device(device_id, payload, qos=0)

        if success:
            logger.info(
                "Ring command sent to %s (dur=%ss), msg_id=%s",
                device_id,
                duration,
                msg_id,
            )
            return msg_id or True
        return None

    def send_ota(self, device_id: str, firmware_url: str) -> bool:
        """
        Send OTA update command to device.

        ESP expects: {"command": "ota", "url": "http://server/firmware/v1.2.3.bin"}
        QoS 1: Ensure delivery - OTA is critical operation
        """
        payload: dict[str, Any] = {"command": "ota", "url": firmware_url}
        success = self.send_to_device(device_id, payload, qos=1)

        if success:
            logger.info("OTA command sent to %s: %s", device_id, firmware_url)

        return success

    def send_ntp_sync(self, device_id: str, ntp_server: str = "pool.ntp.org") -> bool:
        """
        Tell device to sync time via NTP.

        Use when RTC drift detected or after power loss.
        """
        payload: dict[str, Any] = {"command": "ntp_sync", "server": ntp_server}
        return self.send_to_device(device_id, payload, qos=1)

    def send_restart(self, device_id: str) -> str | bool | None:
        """
        Restart device remotely.

        Returns msg_id string on success, None on failure.
        """
        payload: dict[str, Any] = {"command": "reboot"}

        msg_id = self._create_command_log(device_id, "reboot", payload)
        if msg_id:
            payload["msg_id"] = msg_id

        success = self.send_to_device(device_id, payload, qos=1)

        if success:
            logger.warning("Restart command sent to %s", device_id)
            return msg_id or True
        return None

    def send_config(self, device_id: str, config: dict[str, Any]) -> bool:
        """
        Send configuration update to device via config topic.

        For runtime config changes (WiFi settings, logging level, etc.)
        """
        topic = f"devices/{device_id}/config"
        payload: dict[str, Any] = config
        return self.publish(topic, payload, qos=1)

    def send_holidays(
        self,
        device_id: str,
        ranges: list[dict[str, Any]],
        dates: list[dict[str, Any]],
        silent: bool = False,
        version: int = 1,
    ) -> str | None:
        """
        Push holidays (ranges + dates) to device.

        Topic: devices/{device_id}/holidays
        Returns msg_id string on success, None on failure.
        """
        topic = f"devices/{device_id}/holidays"
        payload: dict[str, Any] = {
            "version": version,
            "ranges": ranges,
            "dates": dates,
            "silent": silent,
        }

        msg_id = self._create_command_log(device_id, "holiday_sync", payload)
        if msg_id:
            payload["msg_id"] = msg_id

        success = self.publish(topic, payload, qos=1, retain=True)
        if success:
            return msg_id
        return None

    # ============ Bulk Operations ============

    def broadcast_schedule(
        self,
        device_ids: list[str],
        times: list[str],
        version: int = 0,
        days_mask: int = 0x1F,
        bell_duration: int = 3000,
    ) -> dict[str, str | bool | None]:
        """
        Send same schedule to multiple devices.

        Returns dict of device_id -> msg_id (string), True (success without log),
        or None (failure).
        """
        results: dict[str, str | bool | None] = {}
        for device_id in device_ids:
            results[device_id] = self.send_schedule(
                device_id,
                times,
                version=version,
                days_mask=days_mask,
                bell_duration=bell_duration,
            )
        return results

    def disconnect(self) -> None:
        """Clean disconnect from broker"""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
            logger.info("MQTT Publisher disconnected")


# Global singleton instance
mqtt_publisher: MQTTPublisher = MQTTPublisher()
