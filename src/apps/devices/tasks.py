"""
Celery Tasks for IoT Device Management

WHY Celery for these operations:
1. OTA updates must be throttled (100/hour) - requires delayed execution
2. Schedule sync can be batched - efficiency for 10K devices
3. Daily reports run automatically

Task Categories:
1. OTA Processing - process_ota_batch, check_ota_completion
2. Schedule Sync - sync_pending_schedules
3. Reports - generate_daily_report
"""
import logging
from datetime import timedelta
from typing import Optional

from celery import shared_task
from django.db import OperationalError, transaction
from django.db.models import F, Q as models_Q
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
    queue="emergency",
)
def broadcast_emergency_command(self, device_ids: list[int], payload: dict, chunk_size: int = 50) -> dict:
    """
    Broadcast an emergency command to devices in chunks.
    Runs on the 'emergency' queue for priority routing.
    """
    from apps.devices.models import Device
    from apps.devices.services import mqtt_publisher

    devices = Device.objects.filter(id__in=device_ids).values_list("device_id", flat=True)
    success = 0
    failed = 0

    device_list = list(devices)
    for i in range(0, len(device_list), chunk_size):
        chunk = device_list[i:i + chunk_size]
        for device_id in chunk:
            if mqtt_publisher.send_to_device(device_id, payload):
                success += 1
            else:
                failed += 1

    logger.info(f"Emergency broadcast: {success} success, {failed} failed, payload={payload.get('command')}")
    return {"success": success, "failed": failed, "total": len(device_list)}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
)
def send_bulk_ring(self, device_ids: list[int]) -> dict:
    """
    Send ring command to multiple devices in background.

    Args:
        device_ids: List of Device primary keys to ring.
    """
    from apps.devices.models import Device
    from apps.devices.services import mqtt_publisher

    devices = Device.objects.filter(id__in=device_ids).values_list("device_id", flat=True)
    success = 0
    failed = 0

    for device_id in devices:
        if mqtt_publisher.ring(device_id):
            success += 1
        else:
            failed += 1

    logger.info(f"Bulk ring: {success} success, {failed} failed out of {len(device_ids)}")
    return {"success": success, "failed": failed, "total": len(device_ids)}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
)
def send_bulk_restart(self, device_ids: list[int]) -> dict:
    """
    Send restart command to multiple devices in background.

    Args:
        device_ids: List of Device primary keys to restart.
    """
    from apps.devices.models import Device
    from apps.devices.services import mqtt_publisher

    devices = Device.objects.filter(id__in=device_ids).values_list("device_id", flat=True)
    success = 0
    failed = 0

    for device_id in devices:
        if mqtt_publisher.send_restart(device_id):
            success += 1
        else:
            failed += 1

    logger.info(f"Bulk restart: {success} success, {failed} failed out of {len(device_ids)}")
    return {"success": success, "failed": failed, "total": len(device_ids)}


# ============ OTA Processing Tasks ============

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=300,
    time_limit=360,
)
def process_ota_batch(self, batch_id: int) -> dict:
    """
    Process OTA batch with throttling.
    
    WHY this design:
    1. Rate limiting: devices_per_hour setting
    2. Processes in chunks, re-schedules itself
    3. Handles failures gracefully
    4. Updates progress in real-time
    
    Args:
        batch_id: OTA batch to process
        
    Returns:
        Dict with processing results
    """
    from apps.devices.models import OTABatch, OTABatchDevice
    from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus
    from apps.devices.services import mqtt_publisher
    
    # Use select_for_update to prevent race conditions on concurrent task execution
    with transaction.atomic():
        try:
            batch = OTABatch.objects.select_for_update().select_related("firmware").get(id=batch_id)
        except OTABatch.DoesNotExist:
            logger.error(f"OTA batch {batch_id} not found")
            return {"error": "Batch not found"}
        
        # Check if batch is still active
        if batch.status == OTABatchStatus.CANCELLED:
            logger.info(f"OTA batch {batch_id} was cancelled")
            return {"status": "cancelled"}
        
        if batch.status == OTABatchStatus.COMPLETED:
            logger.info(f"OTA batch {batch_id} already completed")
            return {"status": "already_completed"}
        
        # Mark as in-progress if pending
        if batch.status == OTABatchStatus.PENDING:
            batch.status = OTABatchStatus.IN_PROGRESS
            batch.started_at = timezone.now()
            batch.save(update_fields=["status", "started_at"])
    
    # Calculate chunk size based on rate limit
    # devices_per_hour / 60 minutes * task_interval_minutes
    chunk_size = max(1, batch.devices_per_hour // 6)  # Run every 10 minutes
    
    # Get pending devices
    pending_devices = OTABatchDevice.objects.filter(
        batch=batch,
        status=OTADeviceStatus.PENDING,
    ).select_related("device")[:chunk_size]
    
    if not pending_devices.exists():
        # All devices processed, mark batch complete
        batch.status = OTABatchStatus.COMPLETED
        batch.completed_at = timezone.now()
        batch.save(update_fields=["status", "completed_at"])
        
        logger.info(f"OTA batch {batch_id} completed")
        return {
            "status": "completed",
            "success": batch.success_count,
            "failed": batch.failure_count,
        }
    
    # Process chunk
    firmware_url = batch.firmware.download_url
    processed = 0
    
    for ota_device in pending_devices:
        device = ota_device.device
        
        # Send OTA command (will be delivered when device comes online)
        success = mqtt_publisher.send_ota(device.device_id, firmware_url)
        
        if success:
            ota_device.status = OTADeviceStatus.NOTIFIED
            ota_device.notified_at = timezone.now()
            ota_device.save(update_fields=["status", "notified_at"])
            processed += 1
            
            # Update batch success count atomically
            OTABatch.objects.filter(id=batch_id).update(
                success_count=F("success_count") + 1
            )
            
            logger.info(f"OTA sent to {device.device_id} for batch {batch_id}")
        else:
            ota_device.status = OTADeviceStatus.FAILED
            ota_device.error_message = "MQTT publish failed"
            ota_device.save(update_fields=["status", "error_message"])
            
            # Update batch failure count
            OTABatch.objects.filter(id=batch_id).update(
                failure_count=F("failure_count") + 1
            )
    
    # Schedule next chunk
    remaining = OTABatchDevice.objects.filter(
        batch=batch,
        status=OTADeviceStatus.PENDING,
    ).count()
    
    if remaining > 0:
        # Schedule next run in 10 minutes
        process_ota_batch.apply_async(
            args=[batch_id],
            countdown=600,  # 10 minutes
        )
        
        return {
            "status": "in_progress",
            "processed_this_chunk": processed,
            "remaining": remaining,
        }
    
    # Check for completion
    batch.refresh_from_db()
    batch.status = OTABatchStatus.COMPLETED
    batch.completed_at = timezone.now()
    batch.save(update_fields=["status", "completed_at"])
    
    return {
        "status": "completed",
        "success": batch.success_count,
        "failed": batch.failure_count,
    }


@shared_task(
    bind=True,
    autoretry_for=(OperationalError, ConnectionError),
    max_retries=3,
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
)
def check_ota_completion(self, batch_id: Optional[int] = None, timeout_minutes: int = 30) -> dict:
    """
    Check if notified devices have completed OTA.
    
    Devices that were notified but haven't reported back
    after timeout are marked as failed.

    Args:
        batch_id: OTA batch to check (None = check all active batches)
        timeout_minutes: How long to wait for device response
    """
    from apps.devices.models import OTABatch, OTABatchDevice
    from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus

    timeout_threshold = timezone.now() - timedelta(minutes=timeout_minutes)

    if batch_id is None:
        # Process all in-progress batches inline (no recursive dispatch)
        active_batch_ids = list(
            OTABatch.objects.filter(status=OTABatchStatus.IN_PROGRESS)
            .values_list("id", flat=True)
        )
        total_timed_out = 0
        for bid in active_batch_ids:
            count = OTABatchDevice.objects.filter(
                batch_id=bid,
                status=OTADeviceStatus.NOTIFIED,
                notified_at__lt=timeout_threshold,
            ).update(
                status=OTADeviceStatus.FAILED,
                error_message="OTA timeout - no response from device",
                completed_at=timezone.now(),
            )
            if count > 0:
                OTABatch.objects.filter(id=bid).update(
                    failure_count=F("failure_count") + count
                )
                total_timed_out += count
        if total_timed_out > 0:
            logger.warning(f"Marked {total_timed_out} devices as OTA timeout across {len(active_batch_ids)} batches")
        return {"batches_checked": len(active_batch_ids), "timed_out": total_timed_out}

    try:
        batch = OTABatch.objects.get(id=batch_id)
    except OTABatch.DoesNotExist:
        return {"error": "Batch not found"}

    count = OTABatchDevice.objects.filter(
        batch=batch,
        status=OTADeviceStatus.NOTIFIED,
        notified_at__lt=timeout_threshold,
    ).update(
        status=OTADeviceStatus.FAILED,
        error_message="OTA timeout - no response from device",
        completed_at=timezone.now(),
    )

    if count > 0:
        OTABatch.objects.filter(id=batch_id).update(
            failure_count=F("failure_count") + count
        )
        logger.warning(f"Marked {count} devices as OTA timeout in batch {batch_id}")

    return {"timed_out": count}


# ============ Schedule Sync Tasks ============

@shared_task(
    bind=True,
    autoretry_for=(OperationalError, ConnectionError),
    max_retries=3,
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
)
def sync_pending_schedules(self, max_devices: int = 100) -> dict:
    """
    Sync schedules that are marked as pending.
    
    WHY:
    - Batch processing is more efficient than per-request sync
    - Handles cases where device was offline during API update
    - Runs periodically to catch missed syncs
    - Only syncs to online devices (last_seen within 1 hour)
    
    Args:
        max_devices: Maximum devices to sync in one run
    """
    from apps.devices.models import Schedule
    from apps.devices.services import mqtt_publisher
    
    online_threshold = timezone.now() - timedelta(hours=1)
    
    pending = Schedule.objects.filter(
        sync_pending=True,
        is_active=True,
        device__status="active",
        device__last_seen__gte=online_threshold,
    ).select_related("device")[:max_devices]
    
    success = 0
    failed = 0
    
    for schedule in pending:
        try:
            if mqtt_publisher.send_schedule(
                schedule.device.device_id,
                schedule.times,
                version=schedule.version,
                days_mask=schedule.days_mask,
            ):
                schedule.sync_pending = False
                schedule.synced_at = timezone.now()
                schedule.save(update_fields=["sync_pending", "synced_at"])
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Failed to sync schedule for {schedule.device.device_id}: {e}")
            failed += 1
    
    if success > 0:
        logger.info(f"Synced {success} schedules, {failed} failed")
    
    return {"synced": success, "failed": failed}


@shared_task(
    bind=True,
    autoretry_for=(OperationalError, ConnectionError),
    max_retries=3,
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=60,
    time_limit=90,
)
def detect_stale_schedules(self, stale_days: int = 7) -> dict:
    """
    Detect schedules not synced in stale_days and create alerts.

    WHY:
    - ESP32 operates offline with NVS schedule, but if it hasn't synced
      for 7+ days the schedule may be outdated.
    - Alert is informational — bell still rings with cached schedule.
    """
    from apps.devices.models import Schedule
    from apps.devices.models.device_alert import DeviceAlert

    threshold = timezone.now() - timedelta(days=stale_days)

    stale_schedules = Schedule.objects.filter(
        is_active=True,
        device__status="active",
        device__registration_status="registered",
    ).filter(
        models_Q(synced_at__lt=threshold) | models_Q(synced_at__isnull=True, created_at__lt=threshold)
    ).select_related("device")

    created = 0
    for schedule in stale_schedules:
        _, was_created = DeviceAlert.objects.get_or_create(
            device=schedule.device,
            alert_type=DeviceAlert.AlertType.SCHEDULE_STALE,
            resolved=False,
        )
        if was_created:
            created += 1

    # Auto-resolve stale alerts for schedules that are now fresh
    fresh_device_ids = Schedule.objects.filter(
        is_active=True,
        synced_at__gte=threshold,
    ).values_list("device_id", flat=True)

    resolved = DeviceAlert.objects.filter(
        alert_type="schedule_stale",
        resolved=False,
        device_id__in=fresh_device_ids,
    ).update(resolved=True, resolved_at=timezone.now())

    if created or resolved:
        logger.info(f"Stale schedules: {created} new alerts, {resolved} resolved")

    return {"new_alerts": created, "resolved": resolved}


@shared_task(
    bind=True,
    autoretry_for=(OperationalError, ConnectionError),
    max_retries=3,
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=60,
    time_limit=90,
)
def check_rtc_consecutive_drift(self, drift_threshold_sec: int = 300) -> dict:
    """
    Daily task: increment consecutive drift counter for devices with drift > 5 min.
    If counter reaches 3 → mark rtc_battery_status as 'dead' and create alert.

    Devices with drift <= threshold get their counter reset.

    WHY:
    - Single drift event may be transient (power glitch, etc.)
    - 3 consecutive days confirms battery is actually dying
    - Matches ESP32 firmware RTC diagnostics strategy
    """
    from apps.devices.models import Device
    from apps.devices.models.device_alert import DeviceAlert

    # Increment counter for devices currently drifting > threshold
    drifting = Device.objects.filter(
        status="active",
        registration_status="registered",
        rtc_drift_sec__isnull=False,
        rtc_drift_sec__gt=drift_threshold_sec,
    )
    drifting.update(rtc_consecutive_drift_days=F("rtc_consecutive_drift_days") + 1)

    # Reset counter for devices with acceptable drift
    Device.objects.filter(
        status="active",
        registration_status="registered",
    ).exclude(
        rtc_drift_sec__isnull=False,
        rtc_drift_sec__gt=drift_threshold_sec,
    ).update(rtc_consecutive_drift_days=0)

    # Mark battery dead for devices with 3+ consecutive days
    newly_dead = Device.objects.filter(
        rtc_consecutive_drift_days__gte=3,
        rtc_battery_status__in=["ok", "low"],
    )
    dead_ids = list(newly_dead.values_list("id", flat=True))
    newly_dead.update(rtc_battery_status="dead")

    # Create alerts and notify owners for newly dead batteries
    created = 0
    devices_to_notify = Device.objects.filter(id__in=dead_ids).select_related("owner")
    for device in devices_to_notify:
        _, was_created = DeviceAlert.objects.get_or_create(
            device=device,
            alert_type=DeviceAlert.AlertType.RTC_BATTERY_DEAD,
            resolved=False,
        )
        if was_created:
            created += 1
            notify_rtc_battery_dead.delay(device.id)

    if dead_ids:
        logger.warning(f"RTC battery dead: {len(dead_ids)} devices marked, {created} new alerts")

    return {"drifting": drifting.count() if hasattr(drifting, 'count') else len(dead_ids), "newly_dead": len(dead_ids), "alerts_created": created}


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=30,
    time_limit=45,
)
def notify_rtc_battery_dead(self, device_id: int) -> dict:
    """
    Send Telegram notification when a device's RTC battery is detected as dead.
    """
    import os
    import requests as http_requests
    from apps.devices.models import Device

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return {"status": "skipped", "reason": "not_configured"}

    device = Device.objects.filter(id=device_id).first()
    if not device:
        return {"status": "skipped", "reason": "device_not_found"}

    text = (
        f"🔋 *RTC BATTERY DEAD*\n"
        f"Device: `{device.device_id}`\n"
        f"School: {device.school_name or 'N/A'}\n"
        f"Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Action: RTC batareykasini almashtiring"
    )

    try:
        resp = http_requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return {"status": "sent", "device_id": device.device_id}
    except Exception as e:
        logger.error(f"RTC battery dead notification failed for {device.device_id}: {e}")
        return {"status": "failed", "error": str(e)}


@shared_task(
    bind=True,
    autoretry_for=(OperationalError, ConnectionError),
    max_retries=3,
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=60,
    time_limit=90,
)
def generate_daily_report(self) -> dict:
    """
    Generate daily device health report.
    
    WHY:
    - Provides overview for operations team
    - Can be sent via email or Telegram
    - Tracks trends over time
    """
    from apps.devices.models import Device
    from django.db.models import Count
    
    today = timezone.now().date()
    
    # Device stats
    total_devices = Device.objects.filter(status="active").count()
    registered_devices = Device.objects.filter(
        status="active", 
        registration_status="registered"
    ).count()
    pending_devices = Device.objects.filter(
        status="active",
        registration_status="pending"
    ).count()
    rtc_errors = Device.objects.filter(status="active", rtc_synced=False).count()
    rtc_battery_low = Device.objects.filter(
        status="active", rtc_battery_status__in=["low", "dead"]
    ).count()
    
    # Stale schedules (not synced in 7+ days)
    from apps.devices.models import Schedule
    stale_threshold = timezone.now() - timedelta(days=7)
    stale_schedules = Schedule.objects.filter(
        is_active=True,
        device__status="active",
        device__registration_status="registered",
    ).filter(
        models_Q(synced_at__lt=stale_threshold) | models_Q(synced_at__isnull=True, created_at__lt=stale_threshold)
    ).count()

    # Firmware distribution
    firmware_dist = dict(
        Device.objects.filter(status="active")
        .values("firmware_version")
        .annotate(count=Count("id"))
        .values_list("firmware_version", "count")
    )
    
    report = {
        "date": str(today),
        "total_devices": total_devices,
        "registered_devices": registered_devices,
        "pending_devices": pending_devices,
        "rtc_errors": rtc_errors,
        "rtc_battery_low": rtc_battery_low,
        "stale_schedules": stale_schedules,
        "firmware_distribution": firmware_dist,
    }
    
    logger.info(f"Daily report: {report}")
    
    # TODO: Send via email/Telegram
    # send_telegram_notification(format_report(report))
    
    return report


# ============ Device Health Monitoring Tasks ============

@shared_task(
    bind=True,
    autoretry_for=(OperationalError, ConnectionError),
    max_retries=3,
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
)
def detect_stale_devices(self, threshold_hours: int = 24) -> dict:
    """
    Detect devices with no heartbeat in the given threshold and mark them offline.

    WHY:
    - Devices that stop reporting are likely offline or broken
    - Marking them allows admins to see which devices need attention
    - Runs periodically via Celery beat
    """
    from apps.devices.models import Device
    from django.db.models import Q

    threshold = timezone.now() - timedelta(hours=threshold_hours)

    stale = Device.objects.filter(
        status="active",
        registration_status="registered",
    ).filter(
        Q(last_seen__lt=threshold) | Q(last_seen__isnull=True, created_at__lt=threshold)
    )

    stale_ids = list(stale.values_list("id", flat=True))
    count = stale.update(status="inactive")

    # Create offline alerts for newly-stale devices
    if stale_ids:
        from apps.devices.models.device_alert import DeviceAlert
        alerts = [
            DeviceAlert(device_id=did, alert_type=DeviceAlert.AlertType.OFFLINE)
            for did in stale_ids
        ]
        DeviceAlert.objects.bulk_create(alerts, ignore_conflicts=True)

    if count > 0:
        logger.warning(f"Marked {count} devices as inactive (no heartbeat in {threshold_hours}h)")

    # Update Prometheus gauge
    try:
        from apps.shared.middlewares.prometheus import DEVICE_ONLINE_COUNT, OTA_BATCH_PROGRESS
        online = Device.objects.filter(status="active", registration_status="registered").count()
        DEVICE_ONLINE_COUNT.set(online)

        from apps.devices.models.ota_batch import OTABatchStatus
        from apps.devices.models import OTABatch
        in_progress = OTABatch.objects.filter(status=OTABatchStatus.IN_PROGRESS).count()
        OTA_BATCH_PROGRESS.set(in_progress)
    except Exception:
        pass

    return {"marked_inactive": count}


@shared_task(
    bind=True,
    name="devices.cleanup_device_logs",
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=600,
    time_limit=660,
)
def cleanup_device_logs(self, retention_days: int = 90, chunk_size: int = 2000):
    """
    Delete DeviceLog entries older than retention_days in chunks.

    WHY chunked: A single bulk delete of millions of rows can lock the table,
    spike memory, and block other queries. Deleting in small batches keeps
    transactions short and the database responsive.

    Run periodically (e.g., daily) via Celery Beat.
    """
    from apps.devices.models import DeviceLog

    cutoff = timezone.now() - timedelta(days=retention_days)
    total_deleted = 0

    while True:
        # Get PKs for a chunk to avoid long-running DELETE with subquery
        ids = list(
            DeviceLog.objects.filter(created_at__lt=cutoff)
            .values_list("id", flat=True)[:chunk_size]
        )
        if not ids:
            break
        deleted, _ = DeviceLog.objects.filter(id__in=ids).delete()
        total_deleted += deleted

    if total_deleted:
        logger.info(f"Cleaned up {total_deleted} device logs older than {retention_days} days")
    return {"deleted": total_deleted}


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=30,
    time_limit=45,
)
def notify_panic_alert(self, device_id: str, alert_type: str = "panic") -> dict:
    """
    Send Telegram notification when a panic alert is received from a device.

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from env.
    Silently skips if not configured.
    """
    import os
    import requests as http_requests

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.debug("Telegram not configured, skipping panic notification")
        return {"status": "skipped", "reason": "not_configured"}

    text = f"🚨 *PANIC ALERT*\nDevice: `{device_id}`\nType: {alert_type}\nTime: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}"

    try:
        resp = http_requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return {"status": "sent"}
    except Exception as e:
        logger.error(f"Telegram notification failed: {e}")
        return {"status": "failed", "error": str(e)}


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=60,
    time_limit=90,
)
def sync_ical_schedules(self) -> dict:
    """
    Periodic task: fetch iCal URLs stored in ScheduleTemplate.description
    (lines starting with 'ical:') and update associated schedules.

    Convention: if a ScheduleTemplate has description containing 'ical:https://...',
    we fetch that URL and update the template's times.
    """
    import re
    from apps.devices.models.schedule_template import ScheduleTemplate
    from apps.devices.services.ical_parser import parse_ical_to_times

    updated = 0
    templates = ScheduleTemplate.objects.all()

    for template in templates:
        # Look for ical URL in description
        match = re.search(r"ical:(https://\S+)", template.description)
        if not match:
            continue

        url = match.group(1)

        # SSRF protection: validate + fetch with no redirects
        from apps.devices.services.url_validator import safe_fetch
        content, error = safe_fetch(url, timeout=10, max_bytes=1024 * 1024)
        if error:
            logger.warning(f"Skipping iCal URL for template {template.name}: {error}")
            continue

        try:
            times = parse_ical_to_times(content)
            if times and times != template.times:
                template.times = times
                template.save(update_fields=["times", "updated_at"])
                updated += 1
        except Exception as e:
            logger.warning(f"Failed to parse iCal for template {template.name}: {e}")

    return {"updated": updated, "total_checked": len(templates)}


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=120,
    time_limit=150,
)
def sync_holidays_to_devices(self) -> dict:
    """
    Daily task: sync holiday list (dates + ranges) to all active devices via MQTT.

    Runs at 00:00 — sends the full holiday list so ESP32 can skip bells on holidays.
    """
    import time as _time
    from apps.devices.models import Device
    from apps.devices.models.holiday import Holiday
    from apps.devices.models.holiday_range import HolidayRange
    from apps.devices.services.mqtt_publisher import mqtt_publisher

    # Build holiday dates list
    holidays = Holiday.objects.all()
    dates_list = [{"month": h.date.month, "day": h.date.day} for h in holidays]

    # Build holiday ranges list
    ranges = HolidayRange.objects.filter(device__isnull=True)
    ranges_list = [
        {"from_month": r.from_month, "from_day": r.from_day,
         "to_month": r.to_month, "to_day": r.to_day}
        for r in ranges
    ]

    # Use epoch timestamp as version — always increasing
    version = int(_time.time())

    devices = Device.objects.filter(
        status="active", registration_status="registered"
    ).values_list("device_id", flat=True)

    success = 0
    for device_id in devices:
        if mqtt_publisher.send_holidays(device_id, ranges_list, dates_list, version=version):
            success += 1

    logger.info(f"Holiday sync: {success}/{len(devices)} devices, {len(ranges_list)} ranges, {len(dates_list)} dates")
    return {"synced": success, "total_devices": len(devices)}


@shared_task(
    bind=True,
    max_retries=2,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=30,
    time_limit=45,
    queue="emergency",
)
def auto_clear_silence(self) -> dict:
    """
    End-of-day task: send silent=False to all devices to resume normal operation.

    WHY: When admin presses "Bugun bayram" (today silent), devices stay silent
    until explicitly cancelled. This task auto-clears at 23:59 so next day
    starts with normal bell operation regardless.
    """
    from apps.devices.models import Device
    from apps.devices.services import mqtt_publisher

    device_ids = list(
        Device.objects.filter(status="active", registration_status="registered")
        .values_list("id", flat=True)
    )

    if not device_ids:
        return {"cleared": 0}

    broadcast_emergency_command.delay(device_ids, {"command": "silent", "state": False})
    logger.info(f"Auto-clear silence: queued {len(device_ids)} devices")
    return {"cleared": len(device_ids)}


@shared_task(
    bind=True,
    name="devices.cleanup_bell_logs",
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=300,
    time_limit=360,
)
def cleanup_bell_logs(self, retention_days: int = 30, chunk_size: int = 2000):
    """
    Delete BellLog entries older than retention_days in chunks.

    Bell logs grow fast (every ring event). Keep 30 days by default.
    """
    from apps.devices.models.bell_log import BellLog

    cutoff = timezone.now() - timedelta(days=retention_days)
    total_deleted = 0

    while True:
        ids = list(
            BellLog.objects.filter(rang_at__lt=cutoff)
            .values_list("id", flat=True)[:chunk_size]
        )
        if not ids:
            break
        deleted, _ = BellLog.objects.filter(id__in=ids).delete()
        total_deleted += deleted

    if total_deleted:
        logger.info(f"Cleaned up {total_deleted} bell logs older than {retention_days} days")
    return {"deleted": total_deleted}


@shared_task(
    bind=True,
    name="devices.check_command_timeouts",
    max_retries=2,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    acks_late=True,
    soft_time_limit=30,
    time_limit=45,
)
def check_command_timeouts(self) -> dict:
    """
    Periodic task (every 30s): mark CommandLog entries as 'timeout'
    if status='sent' and sent_at > 30 seconds ago.
    """
    from apps.devices.models.command_log import CommandLog

    cutoff = timezone.now() - timedelta(seconds=30)
    count = CommandLog.objects.filter(
        status="sent", sent_at__lt=cutoff
    ).update(status="timeout")

    if count:
        logger.info(f"Marked {count} commands as timeout")
    return {"timed_out": count}
