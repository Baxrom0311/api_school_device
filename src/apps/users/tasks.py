"""Celery tasks for user-related async operations (email sending)."""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_email_task(self, subject: str, message: str, recipient: str) -> bool:
    """Send email asynchronously via Celery."""
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
        return True
    except Exception as exc:
        logger.warning("Email send failed to %s: %s", recipient, exc)
        raise self.retry(exc=exc)
