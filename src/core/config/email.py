import os

_debug = os.getenv("DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
_default_backend = (
    "django.core.mail.backends.console.EmailBackend" if _debug else "django.core.mail.backends.smtp.EmailBackend"
)

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", _default_backend)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() in {"1", "true", "yes"}
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@schooldevice.uz")
