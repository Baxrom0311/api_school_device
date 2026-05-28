from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0023_holidayrange"),
    ]

    operations = [
        migrations.AddField(
            model_name="schedule",
            name="bell_duration",
            field=models.PositiveIntegerField(
                default=3000,
                help_text="How long the bell rings in milliseconds. Default 3000ms (3s).",
                verbose_name="Bell Duration (ms)",
            ),
        ),
    ]
