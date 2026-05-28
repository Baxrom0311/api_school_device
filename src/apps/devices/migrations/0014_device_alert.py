import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0013_holiday"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceAlert",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("alert_type", models.CharField(choices=[("panic", "Panic"), ("lockdown", "Lockdown"), ("emergency_ring", "Emergency Ring")], max_length=20, verbose_name="alert type")),
                ("resolved", models.BooleanField(default=False, verbose_name="resolved")),
                ("resolved_at", models.DateTimeField(blank=True, null=True, verbose_name="resolved at")),
                ("device", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="alerts", to="devices.device")),
            ],
            options={
                "verbose_name": "Device Alert",
                "verbose_name_plural": "Device Alerts",
                "db_table": "device_alerts",
                "ordering": ["-created_at"],
            },
        ),
    ]
