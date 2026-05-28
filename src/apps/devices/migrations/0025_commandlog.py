import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0024_schedule_bell_duration"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommandLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("msg_id", models.UUIDField(default=uuid.uuid4, unique=True)),
                ("command_type", models.CharField(choices=[("ring", "Ring"), ("schedule_sync", "Schedule Sync"), ("holiday_sync", "Holiday Sync"), ("config", "Config"), ("reboot", "Reboot"), ("fire_alarm", "Fire Alarm")], max_length=20)),
                ("payload", models.JSONField(default=dict)),
                ("status", models.CharField(choices=[("sent", "Sent"), ("delivered", "Delivered"), ("failed", "Failed"), ("timeout", "Timeout")], default="sent", max_length=10)),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
                ("acked_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, default="")),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="command_logs", to="devices.device")),
            ],
            options={
                "ordering": ["-sent_at"],
                "indexes": [
                    models.Index(fields=["status", "sent_at"], name="devices_com_status_sent_idx"),
                ],
            },
        ),
    ]
