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
from django.utils import timezone
from django.db.models import F

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(OperationalError, ConnectionError),
    retry_backoff=True,
    acks_late=True,
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
)
def sync_pending_schedules(self, max_devices: int = 100) -> dict:
    """
    Sync schedules that are marked as pending.
    
    WHY:
    - Batch processing is more efficient than per-request sync
    - Handles cases where device was offline during API update
    - Runs periodically to catch missed syncs
    
    Args:
        max_devices: Maximum devices to sync in one run
    """
    from apps.devices.models import Schedule
    from apps.devices.services import mqtt_publisher
    
    pending = Schedule.objects.filter(
        sync_pending=True,
        is_active=True,
    ).select_related("device")[:max_devices]
    
    success = 0
    failed = 0
    
    for schedule in pending:
        try:
            if mqtt_publisher.send_schedule(
                schedule.device.device_id,
                schedule.times
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

    threshold = timezone.now() - timedelta(hours=threshold_hours)

    stale = Device.objects.filter(
        status="active",
        registration_status="registered",
        updated_at__lt=threshold,
    )

    count = stale.update(status="inactive")

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
