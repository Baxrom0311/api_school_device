import os
import os.path
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent.parent.parent

LOG_DIR = DIR / "assets/logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Check if we're in development mode
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "apps.shared.middlewares.request_id.RequestIDFilter",
        },
    },
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} [req:{request_id}] {message}",
            "style": "{",
        },
        "json": {
            "()": "apps.shared.logging.JSONFormatter",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose" if DEBUG else "json",
            "filters": ["request_id"],
        },
        "file": {
            "level": "INFO",
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "django.log"),
            "when": "midnight",
            "backupCount": 30,
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"] if DEBUG else ["console", "file"],
            "level": "INFO",
            "propagate": True,
        },
        "apps": {
            "handlers": ["console"] if DEBUG else ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
