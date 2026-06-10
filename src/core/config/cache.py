import os

# Redis enabled check
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() in ("true", "1", "yes")

# Cache Configuration
if REDIS_ENABLED:
    # Redis Cache Configuration
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": os.getenv("REDIS_CACHE_URL", "redis://redis:6379/1"),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "CONNECTION_POOL_KWARGS": {"max_connections": 50},
                "SOCKET_CONNECT_TIMEOUT": 5,
                "SOCKET_TIMEOUT": 5,
            },
            "KEY_PREFIX": "iot_device",
        }
    }

    # Session Engine - Redis
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    SESSION_CACHE_ALIAS = "default"

    # Celery Configuration - Redis as broker
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND = "django-db"  # Use django-celery-results
    CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
else:
    # Locmem Cache (Development without Redis)
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "django-cache",
        }
    }

    # Session Engine - Database
    SESSION_ENGINE = "django.contrib.sessions.backends.db"

    # Celery Configuration (Dummy for development)
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "django-db"
    CELERY_TASK_ALWAYS_EAGER = True  # Execute tasks synchronously

# Common Celery settings
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Tashkent"
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_RESULT_EXTENDED = True  # Store additional task metadata
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Cache Middleware Timeout
CACHE_MIDDLEWARE_SECONDS = int(os.getenv("CACHE_TIMEOUT", 300))
