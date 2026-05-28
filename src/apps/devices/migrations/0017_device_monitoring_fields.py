from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0016_schedule_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="rssi",
            field=models.SmallIntegerField(null=True, blank=True, verbose_name="RSSI (dBm)"),
        ),
        migrations.AddField(
            model_name="device",
            name="uptime_sec",
            field=models.PositiveIntegerField(null=True, blank=True, verbose_name="Uptime (seconds)"),
        ),
        migrations.AddField(
            model_name="device",
            name="free_heap",
            field=models.PositiveIntegerField(null=True, blank=True, verbose_name="Free Heap (bytes)"),
        ),
    ]
