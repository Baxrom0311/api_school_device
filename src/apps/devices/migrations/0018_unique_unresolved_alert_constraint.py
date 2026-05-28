from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0017_device_monitoring_fields"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="devicealert",
            constraint=models.UniqueConstraint(
                condition=models.Q(("resolved", False)),
                fields=("device", "alert_type"),
                name="unique_unresolved_alert_per_device",
            ),
        ),
        migrations.AddIndex(
            model_name="belllog",
            index=models.Index(fields=["rang_at"], name="bell_logs_rang_at_idx"),
        ),
    ]
