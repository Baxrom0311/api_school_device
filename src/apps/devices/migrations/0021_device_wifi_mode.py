from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0020_device_rtc_consecutive_drift_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="wifi_mode",
            field=models.CharField(
                choices=[("sta", "STA (Client)"), ("ap", "AP (Access Point)"), ("ap_sta", "AP+STA"), ("disconnected", "Disconnected")],
                default="sta",
                max_length=15,
                verbose_name="WiFi Mode",
            ),
        ),
    ]
