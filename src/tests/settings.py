"""
Test settings - uses SQLite and minimal config for fast test execution.
"""
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DEBUG", "True")

from core.settings import *  # noqa: F401, F403, E402

# Override database to use SQLite for tests
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Faster password hashing for tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Disable default throttling in tests but keep rates for explicit throttle_classes
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    "anon": "1000/min",
    "user": "10000/day",
    "resend_verification": "1000/min",
    "login": "1000/min",
    "forgot_password": "1000/min",
    "reset_password": "1000/min",
    "device_register": "1000/min",
}

# Disable email sending
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
