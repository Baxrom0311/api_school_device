import uuid
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0022_schedule_days_mask"),
    ]

    operations = [
        migrations.CreateModel(
            name="HolidayRange",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=100, verbose_name="name")),
                ("from_month", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)])),
                ("from_day", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(31)])),
                ("to_month", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)])),
                ("to_day", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(31)])),
                ("device", models.ForeignKey(blank=True, help_text="Null = global (applies to all devices)", null=True, on_delete=django.db.models.deletion.CASCADE, related_name="holiday_ranges", to="devices.device")),
            ],
            options={
                "verbose_name": "Holiday Range",
                "verbose_name_plural": "Holiday Ranges",
                "db_table": "holiday_ranges",
            },
        ),
    ]
