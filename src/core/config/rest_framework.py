REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "10000/day",
        "story": "1000/day",
        "resend_verification": "1/min",
        "login": "5/min",
        "forgot_password": "3/hour",
        "reset_password": "5/min",
    },
    "EXCEPTION_HANDLER": "apps.shared.exceptions.auth.custom_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "TITLE": "IoT Device Management API",
    "DESCRIPTION": "API for managing ESP8266 IoT devices, schedules, and OTA updates",
    "VERSION": "1.0.0",
    "TAGS": [
        {"name": "Devices", "description": "Device management and commands"},
        {"name": "Schedules", "description": "Bell schedules for devices"},
        {"name": "Firmware", "description": "Firmware version management"},
        {"name": "OTA Updates", "description": "Over-the-air update batches"},
        {"name": "Device Logs", "description": "Device diagnostic logs"},
    ],
}
