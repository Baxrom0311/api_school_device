from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0021_device_wifi_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="schedule",
            name="days_mask",
            field=models.PositiveSmallIntegerField(
                default=31,
                help_text="Bitmask: bit0=Mon, bit1=Tue, ..., bit6=Sun. Default 0x1F = Mon-Fri",
                verbose_name="Days Mask",
            ),
        ),
    ]
