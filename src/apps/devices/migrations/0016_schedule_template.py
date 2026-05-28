from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0015_bell_log"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScheduleTemplate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=100, verbose_name="name")),
                ("description", models.TextField(blank=True, verbose_name="description")),
                ("times", models.JSONField(help_text='List of times in 24h format, e.g. ["08:00", "08:45"]', verbose_name="times")),
                ("is_default", models.BooleanField(default=False, verbose_name="default")),
            ],
            options={
                "db_table": "schedule_templates",
                "ordering": ["name"],
                "verbose_name": "Schedule Template",
                "verbose_name_plural": "Schedule Templates",
            },
        ),
    ]
