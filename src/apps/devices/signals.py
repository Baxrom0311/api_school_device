"""
Django Signals for Devices App

WHY signals:
1. Auto-create schedule when device is created
2. Invalidate MQTT auth cache on device status change (security)
"""
from django.core.cache import cache
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.devices.models import Device, Schedule


@receiver(post_save, sender=Device)
def create_device_schedule(sender, instance: Device, created: bool, **kwargs):
    """
    Auto-create an empty schedule for new devices.
    
    WHY: Every device needs a schedule, even if empty.
    Prevents null checks throughout the codebase.
    """
    if created:
        Schedule.objects.get_or_create(
            device=instance,
            defaults={
                "times": [],
                "is_active": True,
            }
        )


@receiver(pre_save, sender=Device)
def invalidate_mqtt_cache_on_status_change(sender, instance: Device, **kwargs):
    """
    Invalidate MQTT auth/ACL cache when device status or registration_status changes.

    WHY: Without this, a deactivated device can still connect via MQTT for up to
    5 minutes (cache TTL). This ensures immediate disconnection on status change.
    """
    if not instance.pk:
        return
    try:
        old = Device.objects.only("status", "registration_status").get(pk=instance.pk)
    except Device.DoesNotExist:
        return
    if old.status != instance.status or old.registration_status != instance.registration_status:
        if instance.mqtt_username:
            cache.delete(f"mqtt_auth:{instance.mqtt_username}")
            cache.delete(f"mqtt_acl:{instance.mqtt_username}")
