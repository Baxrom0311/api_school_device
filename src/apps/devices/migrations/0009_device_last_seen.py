from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0008_remove_device_devices_school__85f52e_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='last_seen',
            field=models.DateTimeField(blank=True, help_text='Last heartbeat received from device', null=True, verbose_name='Last Seen'),
        ),
    ]
