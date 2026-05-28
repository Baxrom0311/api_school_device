import uuid
from django.db import models
from apps.shared.models.base import AbstractBaseModel


class CommandLog(AbstractBaseModel):
    COMMAND_TYPES = [
        ("ring", "Ring"),
        ("schedule_sync", "Schedule Sync"),
        ("holiday_sync", "Holiday Sync"),
        ("config", "Config"),
        ("reboot", "Reboot"),
        ("fire_alarm", "Fire Alarm"),
    ]
    STATUS_CHOICES = [
        ("sent", "Sent"),
        ("delivered", "Delivered"),
        ("failed", "Failed"),
        ("timeout", "Timeout"),
    ]

    device = models.ForeignKey("devices.Device", on_delete=models.CASCADE, related_name="command_logs")
    msg_id = models.UUIDField(unique=True, default=uuid.uuid4)
    command_type = models.CharField(max_length=20, choices=COMMAND_TYPES)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="sent")
    sent_at = models.DateTimeField(auto_now_add=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-sent_at"]
        indexes = [
            models.Index(fields=["status", "sent_at"]),
        ]

    def __str__(self):
        return f"{self.device.device_id} - {self.command_type} - {self.status}"
