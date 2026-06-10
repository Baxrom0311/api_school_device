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
import logging
import os
import signal
import sys
import threading
import time
from typing import Any

# Django setup - MUST be before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django  # noqa: E402

django.setup()

import paho.mqtt.client as mqtt  # noqa: E402
from django.db import models, transaction  # noqa: E402
from django.db.models import F  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.devices.models import Device  # noqa: E402
from apps.devices.models.device_log import DeviceLog, LogLevel, LogSource  # noqa: E402


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
    DEVICE_ALERT_TOPIC = "devices/+/alert"  # panic button alerts
    BELL_LOG_TOPIC = "devices/+/bell_log"  # bell ring events
    DEVICE_ACK_TOPIC = "devices/+/ack"  # command acknowledgments
    DEVICE_SYNC_TOPIC = "devices/+/sync"  # reconnect sync requests


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
        ota_device = (
            OTABatchDevice.objects.filter(
                device=device, status__in=[OTADeviceStatus.NOTIFIED, OTADeviceStatus.DOWNLOADING]
            )
            .select_related("batch")
            .first()
        )

        if not ota_device:
            logger.warning(f"No pending OTA found for device {device_id}")
            return

        now = timezone.now()

        if status == "success":
            ota_device.status = OTADeviceStatus.SUCCESS
            ota_device.completed_at = now
            ota_device.save()

            # Update batch counters atomically
            type(ota_device.batch).objects.filter(pk=ota_device.batch.pk).update(success_count=F("success_count") + 1)

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
            type(ota_device).objects.filter(pk=ota_device.pk).update(retry_count=F("retry_count") + 1)

            # Update batch counters atomically
            type(ota_device.batch).objects.filter(pk=ota_device.batch.pk).update(failure_count=F("failure_count") + 1)

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
        self.client: mqtt.Client | None = None
        self._running = False
        self._health_thread: threading.Thread | None = None

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

    def _handle_alert(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle panic/alert message from device. Create DeviceAlert record and notify."""
        from apps.devices.models.device_alert import DeviceAlert
        from apps.devices.tasks import notify_panic_alert

        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            logger.warning(f"Alert from unknown device: {device_id}")
            return

        alert_type = payload.get("type", "panic")

        # RTC drift alert: update device battery status
        if alert_type == "rtc_drift":
            drift_sec = payload.get("drift_sec", 0)
            battery_status = payload.get("battery_status", "low")
            update_fields = {"rtc_synced": False, "rtc_drift_sec": drift_sec}
            if battery_status == "dead":
                update_fields["rtc_battery_status"] = "dead"
                alert_type = "rtc_battery_dead"
            else:
                update_fields["rtc_battery_status"] = "low"
                # Increment consecutive drift days if drift > 5 min
                if drift_sec > 300:
                    from django.db.models import F as db_F

                    Device.objects.filter(id=device.id).update(
                        rtc_consecutive_drift_days=db_F("rtc_consecutive_drift_days") + 1,
                        **update_fields,
                    )
                    # Check if now >= 3 consecutive days → mark dead
                    device.refresh_from_db()
                    if device.rtc_consecutive_drift_days >= 3:
                        Device.objects.filter(id=device.id).update(rtc_battery_status="dead")
                        alert_type = "rtc_battery_dead"
                    DeviceAlert.objects.update_or_create(
                        device=device,
                        alert_type=alert_type,
                        resolved=False,
                        defaults={},
                    )
                    logger.warning(
                        "RTC drift alert from %s: drift=%ss, consecutive=%s",
                        device_id,
                        drift_sec,
                        device.rtc_consecutive_drift_days,
                    )
                    return
            Device.objects.filter(id=device.id).update(**update_fields)
            DeviceAlert.objects.update_or_create(
                device=device,
                alert_type=alert_type,
                resolved=False,
                defaults={},
            )
            logger.warning(f"RTC drift alert from {device_id}: drift={drift_sec}s, battery={battery_status}")
            return

        DeviceAlert.objects.create(device=device, alert_type=alert_type)
        logger.warning(f"ALERT [{alert_type}] from device {device_id}")

        # Dispatch Telegram notification asynchronously
        notify_panic_alert.delay(device_id, alert_type)

    def _handle_ack(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle ACK message from device. Update CommandLog status."""
        from apps.devices.models.command_log import CommandLog

        msg_id = payload.get("msg_id")
        if not msg_id:
            logger.warning(f"ACK from {device_id} missing msg_id")
            return

        try:
            cmd_log = CommandLog.objects.get(msg_id=msg_id)
        except CommandLog.DoesNotExist:
            logger.warning(f"ACK for unknown msg_id={msg_id} from {device_id}")
            return

        ack_status = payload.get("status", "ok")
        now = timezone.now()

        if ack_status == "error":
            cmd_log.status = "failed"
            cmd_log.error_message = payload.get("error", "Device reported error")
        else:
            cmd_log.status = "delivered"

        cmd_log.acked_at = now
        cmd_log.save(update_fields=["status", "acked_at", "error_message"])
        logger.info(f"ACK received: msg_id={msg_id}, status={cmd_log.status}")

    def _handle_bell_log(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle bell ring log from device. Create BellLog record with cache-based rate limiting."""
        from django.core.cache import cache

        from apps.devices.models.bell_log import BellLog

        # Cache-based rate limit: 1 log per device per second (avoids DB query)
        cache_key = f"bell_log_rl:{device_id}"
        if cache.get(cache_key):
            logger.debug(f"Bell log rate limited for {device_id}")
            return
        cache.set(cache_key, 1, timeout=1)

        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            logger.warning(f"Bell log from unknown device: {device_id}")
            return

        BellLog.objects.create(
            device=device,
            rang_at=timezone.now(),
            duration_ms=payload.get("duration", 3000),
            trigger_source=payload.get("source", "schedule"),
        )

    def _handle_sync(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle reconnect sync request from device. Push schedule and holidays if outdated."""
        logger.info(f"Sync request from {device_id}: {payload}")

        # Update last_seen and version telemetry from reconnect payload
        update_fields: dict[str, Any] = {"last_seen": timezone.now()}
        if payload.get("fw"):
            update_fields["firmware_version"] = str(payload["fw"])[:20]
        if payload.get("hw"):
            update_fields["hw_version"] = str(payload["hw"])[:10]
        Device.objects.filter(device_id=device_id).update(**update_fields)

        # Check and push schedule
        try:
            sched_ver = int(payload.get("schedule_version", 0))
        except (TypeError, ValueError):
            sched_ver = 0
        self._check_schedule_version(device_id, sched_ver)

        # Check and push holidays
        self._check_holiday_version(device_id)

    def _check_holiday_version(self, device_id: str) -> None:
        """Push current holidays to device on sync request."""
        import time as _time

        from apps.devices.models.holiday import Holiday
        from apps.devices.models.holiday_range import HolidayRange
        from apps.devices.services.mqtt_publisher import mqtt_publisher

        dates_list = [{"month": h.date.month, "day": h.date.day} for h in Holiday.objects.all()]

        # Global ranges (device=NULL) + device-specific ranges
        ranges_qs = HolidayRange.objects.filter(models.Q(device__isnull=True) | models.Q(device__device_id=device_id))
        ranges_list = [
            {"from_month": r.from_month, "from_day": r.from_day, "to_month": r.to_month, "to_day": r.to_day}
            for r in ranges_qs
        ]

        if not dates_list and not ranges_list:
            return

        version = int(_time.time())
        mqtt_publisher.send_holidays(
            device_id,
            ranges=ranges_list,
            dates=dates_list,
            version=version,
        )
        logger.info(f"Holidays pushed to {device_id} on sync: {len(ranges_list)} ranges, {len(dates_list)} dates")

    def _check_schedule_version(self, device_id: str, device_version: int) -> None:
        """Compare device schedule version with server; push update if outdated."""
        from apps.devices.models import Schedule
        from apps.devices.services.mqtt_publisher import mqtt_publisher

        try:
            schedule = Schedule.objects.select_related("device").get(device__device_id=device_id, is_active=True)
        except Schedule.DoesNotExist:
            return

        if device_version >= schedule.version:
            return

        # Device is outdated — push current schedule
        schedule_kwargs = {"version": schedule.version}
        if schedule.days_mask != 0x1F:
            schedule_kwargs["days_mask"] = schedule.days_mask
        if schedule.bell_duration != 3000:
            schedule_kwargs["bell_duration"] = schedule.bell_duration
        if mqtt_publisher.send_schedule(device_id, schedule.times, **schedule_kwargs):
            schedule.sync_pending = False
            schedule.synced_at = timezone.now()
            schedule.save(update_fields=["sync_pending", "synced_at"])
            logger.info(f"Schedule pushed to {device_id}: device_v={device_version} < server_v={schedule.version}")

    def _health_loop(self):
        """Background thread that periodically writes health to Redis."""
        interval = max(self.config.HEALTH_CHECK_TTL // 2, 10)
        while self._running:
            self._write_health()
            time.sleep(interval)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to broker"""
        if reason_code == 0:
            logger.info(f"Connected to MQTT broker at {self.config.BROKER_HOST}")

            # Subscribe to device topics
            client.subscribe(self.config.OTA_STATUS_TOPIC, qos=1)
            client.subscribe(self.config.DEVICE_STATUS_TOPIC, qos=0)
            client.subscribe(self.config.DEVICE_ALERT_TOPIC, qos=1)
            client.subscribe(self.config.BELL_LOG_TOPIC, qos=1)
            client.subscribe(self.config.DEVICE_ACK_TOPIC, qos=1)
            client.subscribe(self.config.DEVICE_SYNC_TOPIC, qos=1)

            logger.info(
                "Subscribed to: %s, %s, %s, %s, %s, %s",
                self.config.OTA_STATUS_TOPIC,
                self.config.DEVICE_STATUS_TOPIC,
                self.config.DEVICE_ALERT_TOPIC,
                self.config.BELL_LOG_TOPIC,
                self.config.DEVICE_ACK_TOPIC,
                self.config.DEVICE_SYNC_TOPIC,
            )
        else:
            logger.error(f"Connection failed with code: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Callback when disconnected"""
        if reason_code != 0:
            logger.warning(f"Unexpected disconnect: {reason_code}. Will attempt reconnect.")

    MAX_PAYLOAD_SIZE = 65536  # 64KB max MQTT payload

    def _on_message(self, client, userdata, msg):
        """Callback for incoming messages"""
        try:
            topic = msg.topic

            # Reject oversized payloads to prevent OOM
            if len(msg.payload) > self.MAX_PAYLOAD_SIZE:
                logger.warning(f"Payload too large on {topic}: {len(msg.payload)} bytes, dropping")
                return

            payload = json.loads(msg.payload.decode("utf-8"))

            logger.debug(f"Received on {topic}: {payload}")

            # Route messages based on topic pattern
            # devices/{device_id}/ota/status
            # devices/{device_id}/status
            parts = topic.split("/")
            if len(parts) < 3:
                return

            device_id = parts[1]

            # Validate device_id format. MAC-style IDs may include colons.
            if not device_id or len(device_id) > 64 or not all(c.isalnum() or c in "-_:" for c in device_id):
                logger.warning(f"Invalid device_id in topic: {topic}")
                return

            if topic.endswith("/ota/status"):
                OTAStatusHandler.handle(device_id, payload)
            elif topic.endswith("/ack"):
                self._handle_ack(device_id, payload)
            elif topic.endswith("/alert"):
                # Panic button or device alert
                self._handle_alert(device_id, payload)
            elif topic.endswith("/sync"):
                self._handle_sync(device_id, payload)
            elif topic.endswith("/bell_log"):
                self._handle_bell_log(device_id, payload)
            elif topic.endswith("/status") and not topic.endswith("/ota/status"):
                # Heartbeat — update last_seen and monitoring fields
                now = timezone.now()
                update_fields: dict[str, Any] = {"last_seen": now}
                if payload.get("status") == "offline":
                    update_fields["wifi_mode"] = "disconnected"
                if "rssi" in payload:
                    update_fields["rssi"] = int(payload["rssi"])
                if "uptime" in payload:
                    update_fields["uptime_sec"] = int(payload["uptime"])
                if "heap" in payload:
                    update_fields["free_heap"] = int(payload["heap"])
                if payload.get("fw"):
                    update_fields["firmware_version"] = str(payload["fw"])[:20]
                if payload.get("hw"):
                    update_fields["hw_version"] = str(payload["hw"])[:10]
                if "wifi_mode" in payload:
                    wm = payload["wifi_mode"]
                    if wm in ("sta", "ap", "ap_sta", "disconnected"):
                        update_fields["wifi_mode"] = wm
                if payload.get("rtc_ok"):
                    update_fields["rtc_synced"] = True
                    update_fields["rtc_battery_status"] = "ok"
                    update_fields["rtc_drift_sec"] = None
                    update_fields["rtc_consecutive_drift_days"] = 0
                # Handle rtc_battery/rtc_drift_sec from heartbeat
                if "rtc_battery" in payload:
                    battery = payload["rtc_battery"]
                    if battery in ("ok", "low", "dead"):
                        update_fields["rtc_battery_status"] = battery
                    if battery == "ok":
                        update_fields["rtc_synced"] = True
                        update_fields["rtc_consecutive_drift_days"] = 0
                if "rtc_drift_sec" in payload:
                    update_fields["rtc_drift_sec"] = int(payload["rtc_drift_sec"])
                if "rtc_consecutive_drift_days" in payload:
                    update_fields["rtc_consecutive_drift_days"] = int(payload["rtc_consecutive_drift_days"])
                Device.objects.filter(device_id=device_id).update(**update_fields)

                # Auto-resolve RTC alerts when device reports battery OK
                if payload.get("rtc_ok") or payload.get("rtc_battery") == "ok":
                    from apps.devices.models.device_alert import DeviceAlert

                    DeviceAlert.objects.filter(
                        device__device_id=device_id,
                        alert_type__in=["rtc_drift", "rtc_battery_dead"],
                        resolved=False,
                    ).update(resolved=True, resolved_at=now)

                # Schedule version check: push new schedule if device is outdated
                sched_ver = payload.get("schedule_version") or payload.get("sched_ver")
                if sched_ver is not None:
                    try:
                        self._check_schedule_version(device_id, int(sched_ver))
                    except (TypeError, ValueError):
                        logger.warning(f"Invalid schedule version from {device_id}: {sched_ver}")

                reactivated = Device.objects.filter(device_id=device_id, status="inactive").update(status="active")
                if reactivated:
                    try:
                        device = Device.objects.get(device_id=device_id)
                        DeviceLog.objects.create(
                            device=device,
                            level=LogLevel.INFO,
                            source=LogSource.MQTT,
                            message="Device reconnected (was inactive)",
                        )
                        # Auto-resolve offline alerts for this device
                        from apps.devices.models.device_alert import DeviceAlert

                        DeviceAlert.objects.filter(device=device, alert_type="offline", resolved=False).update(
                            resolved=True, resolved_at=now
                        )
                    except Device.DoesNotExist:
                        pass

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON on {msg.topic}: {e}")
        except Exception as e:
            logger.exception(f"Error processing message: {e}")

    def start(self):
        """Start the listener service"""
        logger.info("Starting MQTT Listener Service...")

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.config.CLIENT_ID,
            protocol=mqtt.MQTTv311,
        )

        # Set callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # Authentication
        if self.config.USERNAME and self.config.PASSWORD:
            self.client.username_pw_set(self.config.USERNAME, self.config.PASSWORD)

        # TLS
        if self.config.USE_TLS:
            self.client.tls_set(ca_certs=self.config.TLS_CA_CERTS)

        # Enable auto-reconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=120)

        try:
            self.client.connect(self.config.BROKER_HOST, self.config.BROKER_PORT, keepalive=60)

            self._running = True

            # Start health heartbeat thread
            self._health_thread = threading.Thread(target=self._health_loop, daemon=True)
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
