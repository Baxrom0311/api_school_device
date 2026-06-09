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
import json
import os
import logging
import threading
import time
from typing import Any, Optional
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from apps.shared.middlewares.prometheus import MQTT_PUBLISH_TOTAL
except Exception:
    MQTT_PUBLISH_TOTAL = None


# ============ Circuit Breaker ============

class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open and calls are rejected."""
    pass


class CircuitBreaker:
    """
    Simple circuit breaker to avoid hammering a down MQTT broker.

    States: CLOSED (normal) -> OPEN (failing) -> HALF_OPEN (testing recovery)
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self._state = self.CLOSED
        self._failure_count = 0
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._last_failure_time: float = 0
        self._lock = threading.Lock()

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
                    f"Circuit breaker OPEN after {self._failure_count} failures. "
                    f"Will retry in {self._recovery_timeout}s."
                )

    def allow_request(self) -> bool:
        state = self.state
        return state in (self.CLOSED, self.HALF_OPEN)


@dataclass
class MQTTConfig:
    """MQTT broker configuration"""
    host: str = "localhost"
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: str = "django-publisher"
    keepalive: int = 60
    use_tls: bool = False
    
    @classmethod
    def from_env(cls) -> "MQTTConfig":
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


class MQTTPublisher:
    """
    Thread-safe MQTT publisher for sending commands to devices.
    
    Usage:
        from apps.devices.services import mqtt_publisher
        
        mqtt_publisher.send_schedule("device_001", ["08:30", "09:15"])
        mqtt_publisher.ring("device_001", duration=5)
        mqtt_publisher.send_ota("device_001", "http://server/firmware/v1.2.3.bin")
    """
    
    _instance: Optional["MQTTPublisher"] = None
    _lock = threading.Lock()
    
    def __new__(cls, config: Optional[MQTTConfig] = None):
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

    def __init__(self, config: Optional[MQTTConfig] = None):
        pass
        
    def _get_client(self) -> mqtt.Client:
        """Get or create MQTT client with lazy connection"""
        with self._connect_lock:
            if self._client is None or not self._connected:
                self._connect()
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
                self._client.username_pw_set(
                    self.config.username,
                    self.config.password
                )
            
            # TLS
            if self.config.use_tls:
                self._client.tls_set()
            
            # Connect
            self._client.connect(
                self.config.host,
                self.config.port,
                self.config.keepalive
            )
            
            # Start background loop for handling callbacks
            self._client.loop_start()
            
            logger.info(
                f"MQTT Publisher connecting to {self.config.host}:{self.config.port}"
            )
            
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self._connected = False
            raise
    
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to broker"""
        if reason_code == 0:
            self._connected = True
            logger.info("MQTT Publisher connected successfully")
        else:
            self._connected = False
            logger.error(f"MQTT connection failed with code: {reason_code}")
    
    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Callback when disconnected from broker"""
        self._connected = False
        if reason_code != 0:
            logger.warning(f"MQTT unexpected disconnect: {reason_code}")

    def is_connected(self) -> bool:
        """Check if MQTT client is currently connected"""
        return self._connected
    
    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        qos: int = 1,
        retain: bool = False
    ) -> bool:
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
            logger.warning(f"Circuit breaker OPEN, dropping publish to {topic}")
            if MQTT_PUBLISH_TOTAL:
                MQTT_PUBLISH_TOTAL.labels(result="circuit_open").inc()
            return False

        try:
            client = self._get_client()
            message = json.dumps(payload)
            
            result = client.publish(topic, message, qos=qos, retain=retain)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published to {topic}: {message}")
                self._circuit_breaker.record_success()
                if MQTT_PUBLISH_TOTAL:
                    MQTT_PUBLISH_TOTAL.labels(result="success").inc()
                return True
            else:
                logger.error(f"Publish failed to {topic}: rc={result.rc}")
                self._circuit_breaker.record_failure()
                if MQTT_PUBLISH_TOTAL:
                    MQTT_PUBLISH_TOTAL.labels(result="failure").inc()
                return False
                
        except Exception as e:
            logger.error(f"Publish error: {e}")
            self._circuit_breaker.record_failure()
            if MQTT_PUBLISH_TOTAL:
                MQTT_PUBLISH_TOTAL.labels(result="failure").inc()
            return False
    
    def send_to_device(
        self,
        device_id: str,
        payload: dict[str, Any],
        qos: int = 1
    ) -> bool:
        """
        Send command to specific device.
        
        Topic format: devices/{device_id}/command
        """
        topic = f"devices/{device_id}/command"
        return self.publish(topic, payload, qos=qos)
    
    # ============ Command Helpers ============
    
    def _create_command_log(self, device_id: str, command_type: str, payload: dict) -> Optional[str]:
        """Create CommandLog and return msg_id string. Returns None if device not found."""
        try:
            from apps.devices.models import Device
            from apps.devices.models.command_log import CommandLog
            import uuid
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
            logger.warning(f"Failed to create CommandLog for {device_id}: {e}")
            return None

    def send_schedule(self, device_id: str, times: list[str], version: int = 0, days_mask: int = 0x1F, bell_duration: int = 3000) -> Optional[str]:
        """
        Push schedule to device via schedule topic.
        
        Returns msg_id string on success, None on failure.
        """
        entries = []
        for t in times:
            parts = t.split(":")
            if len(parts) == 2:
                entries.append({
                    "hour": int(parts[0]),
                    "minute": int(parts[1]),
                    "duration": bell_duration,
                    "days": days_mask,
                })
        
        topic = f"devices/{device_id}/schedule"
        payload = {"version": version, "entries": entries}
        
        msg_id = self._create_command_log(device_id, "schedule_sync", payload)
        if msg_id:
            payload["msg_id"] = msg_id
        
        success = self.publish(topic, payload, qos=1)
        
        if success:
            logger.info(f"Schedule sent to {device_id}: {len(entries)} entries, msg_id={msg_id}")
            return msg_id
        return None
    
    def ring(self, device_id: str, duration: int = 5) -> Optional[str]:
        """
        Trigger immediate ring on device.
        
        Returns msg_id string on success, None on failure.
        """
        payload = {"command": "ring", "duration": duration}
        
        msg_id = self._create_command_log(device_id, "ring", payload)
        if msg_id:
            payload["msg_id"] = msg_id
        
        success = self.send_to_device(device_id, payload, qos=0)
        
        if success:
            logger.info(f"Ring command sent to {device_id} (dur={duration}s), msg_id={msg_id}")
            return msg_id
        return None
    
    def send_ota(self, device_id: str, firmware_url: str) -> bool:
        """
        Send OTA update command to device.
        
        ESP expects: {"command": "ota", "url": "http://server/firmware/v1.2.3.bin"}
        QoS 1: Ensure delivery - OTA is critical operation
        """
        payload = {"command": "ota", "url": firmware_url}
        success = self.send_to_device(device_id, payload, qos=1)
        
        if success:
            logger.info(f"OTA command sent to {device_id}: {firmware_url}")
        
        return success
    
    def send_ntp_sync(self, device_id: str, ntp_server: str = "pool.ntp.org") -> bool:
        """
        Tell device to sync time via NTP.
        
        Use when RTC drift detected or after power loss.
        """
        payload = {"command": "ntp_sync", "server": ntp_server}
        return self.send_to_device(device_id, payload, qos=1)
    
    def send_restart(self, device_id: str) -> Optional[str]:
        """
        Restart device remotely.
        
        Returns msg_id string on success, None on failure.
        """
        payload = {"command": "reboot"}
        
        msg_id = self._create_command_log(device_id, "reboot", payload)
        if msg_id:
            payload["msg_id"] = msg_id
        
        success = self.send_to_device(device_id, payload, qos=1)
        
        if success:
            logger.warning(f"Restart command sent to {device_id}")
            return msg_id
        return None
    
    def send_config(
        self,
        device_id: str,
        config: dict[str, Any]
    ) -> bool:
        """
        Send configuration update to device via config topic.
        
        For runtime config changes (WiFi settings, logging level, etc.)
        """
        topic = f"devices/{device_id}/config"
        payload = config
        return self.publish(topic, payload, qos=1)

    def send_holidays(
        self,
        device_id: str,
        ranges: list[dict],
        dates: list[dict],
        silent: bool = False,
        version: int = 1,
    ) -> Optional[str]:
        """
        Push holidays (ranges + dates) to device.

        Topic: devices/{device_id}/holidays
        Returns msg_id string on success, None on failure.
        """
        topic = f"devices/{device_id}/holidays"
        payload = {
            "version": version,
            "ranges": ranges,
            "dates": dates,
            "silent": silent,
        }

        msg_id = self._create_command_log(device_id, "holiday_sync", payload)
        if msg_id:
            payload["msg_id"] = msg_id

        success = self.publish(topic, payload, qos=1)
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
    ) -> dict[str, bool]:
        """
        Send same schedule to multiple devices.
        
        Returns dict of device_id -> success status
        """
        results = {}
        for device_id in device_ids:
            results[device_id] = self.send_schedule(device_id, times, version=version, days_mask=days_mask, bell_duration=bell_duration)
        return results
    
    def disconnect(self) -> None:
        """Clean disconnect from broker"""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
            logger.info("MQTT Publisher disconnected")


# Global singleton instance
mqtt_publisher = MQTTPublisher()
