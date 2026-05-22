"""
MQTT Publisher Service - Sends commands to ESP8266 devices.

WHY this design:
1. Singleton pattern for connection reuse - MQTT connections are expensive
2. Thread-safe publishing with connection management
3. QoS 1 for important commands (schedule, OTA) to ensure delivery
4. QoS 0 for ring commands (fire-and-forget, real-time)
5. Automatic reconnection handling
6. Structured command helpers for type safety
"""
import json
import os
import logging
import threading
from typing import Any, Optional
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from apps.shared.middlewares.prometheus import MQTT_PUBLISH_TOTAL
except Exception:
    MQTT_PUBLISH_TOTAL = None


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
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config: Optional[MQTTConfig] = None):
        if self._initialized:
            return
            
        self.config = config or MQTTConfig.from_env()
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._connect_lock = threading.Lock()
        self._initialized = True
        
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
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker"""
        if rc == 0:
            self._connected = True
            logger.info("MQTT Publisher connected successfully")
        else:
            self._connected = False
            logger.error(f"MQTT connection failed with code: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker"""
        self._connected = False
        if rc != 0:
            logger.warning(f"MQTT unexpected disconnect: {rc}")

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
        """
        try:
            client = self._get_client()
            message = json.dumps(payload)
            
            result = client.publish(topic, message, qos=qos, retain=retain)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published to {topic}: {message}")
                if MQTT_PUBLISH_TOTAL:
                    MQTT_PUBLISH_TOTAL.labels(result="success").inc()
                return True
            else:
                logger.error(f"Publish failed to {topic}: rc={result.rc}")
                if MQTT_PUBLISH_TOTAL:
                    MQTT_PUBLISH_TOTAL.labels(result="failure").inc()
                return False
                
        except Exception as e:
            logger.error(f"Publish error: {e}")
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
    
    def send_schedule(self, device_id: str, times: list[str]) -> bool:
        """
        Push schedule to device via schedule topic.
        
        Converts times list ["08:30", "09:15"] to ESP32 format:
        {"entries": [{"hour": 8, "minute": 30, "duration": 3000, "days": 127}, ...]}
        
        QoS 1: Ensure delivery - schedules are critical
        """
        entries = []
        for t in times:
            parts = t.split(":")
            if len(parts) == 2:
                entries.append({
                    "hour": int(parts[0]),
                    "minute": int(parts[1]),
                    "duration": 3000,  # 3 seconds default bell duration
                    "days": 0x1F,  # Mon-Fri (bits 0-4)
                })
        
        topic = f"devices/{device_id}/schedule"
        payload = {"entries": entries}
        success = self.publish(topic, payload, qos=1)
        
        if success:
            logger.info(f"Schedule sent to {device_id}: {len(entries)} entries")
        
        return success
    
    def ring(self, device_id: str, duration: int = 5) -> bool:
        """
        Trigger immediate ring on device.
        
        ESP expects: {"command": "ring", "duration": 5}
        QoS 0: Fire-and-forget for real-time responsiveness
        """
        payload = {"command": "ring", "duration": duration}
        success = self.send_to_device(device_id, payload, qos=0)
        
        if success:
            logger.info(f"Ring command sent to {device_id} (dur={duration}s)")
        
        return success
    
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
    
    def send_restart(self, device_id: str) -> bool:
        """
        Restart device remotely.
        
        Use for troubleshooting or applying settings.
        """
        payload = {"command": "reboot"}
        success = self.send_to_device(device_id, payload, qos=1)
        
        if success:
            logger.warning(f"Restart command sent to {device_id}")
        
        return success
    
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
    
    # ============ Bulk Operations ============
    
    def broadcast_schedule(
        self,
        device_ids: list[str],
        times: list[str]
    ) -> dict[str, bool]:
        """
        Send same schedule to multiple devices.
        
        Returns dict of device_id -> success status
        """
        results = {}
        for device_id in device_ids:
            results[device_id] = self.send_schedule(device_id, times)
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
