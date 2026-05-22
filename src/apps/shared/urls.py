from django.conf import settings
from django.urls import path

from apps.shared.views.base import HomeView
from apps.shared.views.health import HealthCheckView, LivenessView, ReadinessView

urlpatterns = [
    path("api/v1/health/", HealthCheckView.as_view(), name="health_check"),
    path("api/v1/health/live", LivenessView.as_view(), name="health_live"),
    path("api/v1/health/ready", ReadinessView.as_view(), name="health_ready"),
]

if settings.DEBUG:
    urlpatterns += [
        path("", HomeView.as_view(), name="home"),
    ]
