#!/usr/bin/env python
"""
MQTT Listener Service - Receives OTA status updates from ESP8266 devices.

WHY this runs as a separate service (not inside Django):
1. MQTT requires persistent connection - Django request/response cycle doesn't fit
2. Needs to run 24/7 independently of web workers
3. Can be scaled separately from web API
4. Clean separation of concerns

Run as:
    python mqtt_listener.py

Production deployment:
    - systemd service
    - Docker container
    - Supervisor process

Message format from ESP:
{
    "status": "success" | "failed",
    "error": "optional error message"
}
"""
import json
import os
import sys
import signal
import logging
import time
import threading
from typing import Any, Optional

# Django setup - MUST be before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django
django.setup()

import paho.mqtt.client as mqtt
from django.utils import timezone
from django.db import transaction
from django.db.models import F

from apps.devices.models import Device
from apps.devices.models.device_log import DeviceLog, LogLevel, LogSource

# Configure logging with JSON formatter for structured logging
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
)
logger = logging.getLogger("mqtt_listener")


class MQTTListenerConfig:
    """Configuration from environment"""
    BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
    BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    USERNAME = os.getenv("MQTT_USERNAME")
    PASSWORD = os.getenv("MQTT_PASSWORD")
    CLIENT_ID = os.getenv("MQTT_LISTENER_CLIENT_ID", "django-listener")
    USE_TLS = os.getenv("MQTT_USE_TLS", "false").lower() == "true"
    TLS_CA_CERTS = os.getenv("MQTT_TLS_CA_CERTS")  # Path to CA cert file
    HEALTH_CHECK_TTL = int(os.getenv("MQTT_LISTENER_HEALTH_TTL", "60"))
    
    # Topics to subscribe
    OTA_STATUS_TOPIC = "devices/+/ota/status"  # + is single-level wildcard
    DEVICE_STATUS_TOPIC = "devices/+/status"  # heartbeat/online/offline


class OTAStatusHandler:
    """
    Processes OTA update status messages from devices.
    
    ESP sends status after OTA attempt:
    {"status": "success"} or {"status": "failed", "error": "..."}
    """
    
    @staticmethod
    @transaction.atomic
    def handle(device_id: str, payload: dict[str, Any]) -> None:
        """Process OTA status from device"""
        from apps.devices.models import OTABatchDevice
        from apps.devices.models.ota_batch import OTADeviceStatus
        
        status = payload.get("status")
        
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            logger.warning(f"OTA status from unknown device: {device_id}")
            return
        
        # Find pending OTA update for this device
        ota_device = OTABatchDevice.objects.filter(
            device=device,
            status__in=[OTADeviceStatus.NOTIFIED, OTADeviceStatus.DOWNLOADING]
        ).select_related("batch").first()
        
        if not ota_device:
            logger.warning(f"No pending OTA found for device {device_id}")
            return
        
        now = timezone.now()
        
        if status == "success":
            ota_device.status = OTADeviceStatus.SUCCESS
            ota_device.completed_at = now
            ota_device.save()
            
            # Update batch counters atomically
            type(ota_device.batch).objects.filter(pk=ota_device.batch.pk).update(
                success_count=F("success_count") + 1
            )
            
            logger.info(f"OTA success for {device_id}")
            
            DeviceLog.objects.create(
                device=device,
                level=LogLevel.INFO,
                source=LogSource.DEVICE,
                message=f"OTA update successful: {ota_device.batch.firmware.version}",
            )
            
        elif status == "failed":
            ota_device.status = OTADeviceStatus.FAILED
            ota_device.error_message = payload.get("error", "Unknown error")
            ota_device.completed_at = now
            ota_device.save()
            
            # Update retry_count atomically
            type(ota_device).objects.filter(pk=ota_device.pk).update(
                retry_count=F("retry_count") + 1
            )
            
            # Update batch counters atomically
            type(ota_device.batch).objects.filter(pk=ota_device.batch.pk).update(
                failure_count=F("failure_count") + 1
            )
            
            logger.error(f"OTA failed for {device_id}: {ota_device.error_message}")
            
            DeviceLog.objects.create(
                device=device,
                level=LogLevel.ERROR,
                source=LogSource.DEVICE,
                message=f"OTA update failed: {ota_device.error_message}",
                metadata=payload,
            )


class MQTTListener:
    """
    Main MQTT listener service.
    
    Subscribes to device topics and dispatches messages to handlers.
    Writes a health key to Redis with TTL for external monitoring.
    """
    
    HEALTH_REDIS_KEY = "mqtt_listener:alive"
    
    def __init__(self):
        self.config = MQTTListenerConfig()
        self.client: Optional[mqtt.Client] = None
        self._running = False
        self._health_thread: Optional[threading.Thread] = None
    
    def _write_health(self):
        """Write health key to Redis with TTL so monitors can detect if listener dies."""
        try:
            from django.core.cache import cache
            cache.set(
                self.HEALTH_REDIS_KEY,
                {"status": "alive", "ts": int(time.time())},
                self.config.HEALTH_CHECK_TTL,
            )
        except Exception as e:
            logger.warning(f"Failed to write health key to Redis: {e}")
    
    def _health_loop(self):
        """Background thread that periodically writes health to Redis."""
        interval = max(self.config.HEALTH_CHECK_TTL // 2, 10)
        while self._running:
            self._write_health()
            time.sleep(interval)
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker"""
        if rc == 0:
            logger.info(f"Connected to MQTT broker at {self.config.BROKER_HOST}")
            
            # Subscribe to device topics
            client.subscribe(self.config.OTA_STATUS_TOPIC, qos=1)
            client.subscribe(self.config.DEVICE_STATUS_TOPIC, qos=0)
            
            logger.info(f"Subscribed to: {self.config.OTA_STATUS_TOPIC}, {self.config.DEVICE_STATUS_TOPIC}")
        else:
            logger.error(f"Connection failed with code: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected"""
        if rc != 0:
            logger.warning(f"Unexpected disconnect: {rc}. Will attempt reconnect.")
    
    def _on_message(self, client, userdata, msg):
        """Callback for incoming messages"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode("utf-8"))
            
            logger.debug(f"Received on {topic}: {payload}")
            
            # Route messages based on topic pattern
            # devices/{device_id}/ota/status
            # devices/{device_id}/status
            parts = topic.split("/")
            if len(parts) < 3:
                return
            
            device_id = parts[1]
            
            if topic.endswith("/ota/status"):
                OTAStatusHandler.handle(device_id, payload)
            elif topic.endswith("/status") and not topic.endswith("/ota/status"):
                # Heartbeat — update last_seen; reactivate only if was inactive
                now = timezone.now()
                Device.objects.filter(device_id=device_id).update(last_seen=now)
                Device.objects.filter(
                    device_id=device_id, status="inactive"
                ).update(status="active")
                    
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON on {msg.topic}: {e}")
        except Exception as e:
            logger.exception(f"Error processing message: {e}")
    
    def start(self):
        """Start the listener service"""
        logger.info("Starting MQTT Listener Service...")
        
        self.client = mqtt.Client(
            client_id=self.config.CLIENT_ID,
            protocol=mqtt.MQTTv311,
        )
        
        # Set callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
        # Authentication
        if self.config.USERNAME and self.config.PASSWORD:
            self.client.username_pw_set(
                self.config.USERNAME,
                self.config.PASSWORD
            )
        
        # TLS
        if self.config.USE_TLS:
            self.client.tls_set(ca_certs=self.config.TLS_CA_CERTS)
        
        # Enable auto-reconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=120)
        
        try:
            self.client.connect(
                self.config.BROKER_HOST,
                self.config.BROKER_PORT,
                keepalive=60
            )
            
            self._running = True
            
            # Start health heartbeat thread
            self._health_thread = threading.Thread(
                target=self._health_loop, daemon=True
            )
            self._health_thread.start()
            
            # Blocking loop - runs until stop() called
            self.client.loop_forever()
            
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.exception(f"Fatal error: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the listener service"""
        self._running = False
        if self.client:
            self.client.disconnect()
            logger.info("MQTT Listener stopped")


def main():
    """Entry point for MQTT listener service"""
    listener = MQTTListener()
    
    # Handle shutdown signals gracefully
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        listener.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    listener.start()


if __name__ == "__main__":
    main()
