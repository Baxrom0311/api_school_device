import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0014_device_alert"),
    ]

    operations = [
        migrations.CreateModel(
            name="BellLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("rang_at", models.DateTimeField(verbose_name="rang at")),
                ("duration_ms", models.PositiveIntegerField(verbose_name="duration (ms)")),
                ("trigger_source", models.CharField(choices=[("schedule", "Schedule"), ("manual", "Manual"), ("emergency", "Emergency"), ("mqtt", "MQTT Command")], default="schedule", max_length=20, verbose_name="trigger source")),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bell_logs", to="devices.device")),
            ],
            options={
                "verbose_name": "Bell Log",
                "verbose_name_plural": "Bell Logs",
                "db_table": "bell_logs",
                "ordering": ["-rang_at"],
            },
        ),
        migrations.AddIndex(
            model_name="belllog",
            index=models.Index(fields=["device", "-rang_at"], name="bell_logs_device__b2e3a4_idx"),
        ),
    ]
