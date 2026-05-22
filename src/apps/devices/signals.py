"""
Django Signals for Devices App

WHY signals:
1. Auto-create schedule when device is created
2. Trigger MQTT sync on schedule change
"""
from django.db.models.signals import post_save
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
