from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0019_device_rtc_battery_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="rtc_consecutive_drift_days",
            field=models.PositiveSmallIntegerField(
                default=0,
                verbose_name="Consecutive RTC Drift Days",
                help_text="Days in a row with drift > 5 min. 3+ = battery dead.",
            ),
        ),
    ]
