THIRD_PARTY_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.import_export",
    "unfold.contrib.guardian",
    "unfold.contrib.simple_history",
    "modeltranslation",
    "django_ckeditor_5",
    "corsheaders",
    "rosetta",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_prometheus",
    "django_celery_beat",  # Celery Beat Scheduler
    "django_celery_results",  # Celery Task Results
]

import os  # noqa: E402

if os.getenv("DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}:
    try:
        import silk  # noqa: F401

        THIRD_PARTY_APPS.append("silk")
    except ImportError:
        pass

DEFAULT_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

PROJECT_APPS = [
    "apps.shared.apps.SharedConfig",
    "apps.users.apps.UsersConfig",
    "apps.devices.apps.DevicesConfig",
]
