from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0018_unique_unresolved_alert_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="rtc_battery_status",
            field=models.CharField(
                max_length=10,
                choices=[("ok", "OK"), ("low", "Low"), ("dead", "Dead")],
                default="ok",
                verbose_name="RTC Battery Status",
            ),
        ),
        migrations.AddField(
            model_name="device",
            name="rtc_drift_sec",
            field=models.IntegerField(
                null=True,
                blank=True,
                verbose_name="Last RTC Drift (seconds)",
            ),
        ),
    ]
