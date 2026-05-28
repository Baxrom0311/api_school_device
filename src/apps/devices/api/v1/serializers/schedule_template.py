from rest_framework import serializers

from apps.devices.models.schedule_template import ScheduleTemplate


class ScheduleTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleTemplate
        fields = ["id", "name", "description", "times", "is_default", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
