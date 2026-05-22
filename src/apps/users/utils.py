from django.conf import settings

from apps.users.tasks import send_email_task


def send_verification_email(email: str, token: str) -> None:
    """Send email verification token to user (async via Celery)."""
    subject = "Email tasdiqlash — School Device"
    message = (
        f"Emailingizni tasdiqlash uchun quyidagi kodni kiriting:\n\n"
        f"{token}\n\n"
        f"Agar siz ro'yxatdan o'tmagan bo'lsangiz, ushbu xabarni e'tiborsiz qoldiring.\n"
        f"Kod 24 soat ichida amal qiladi."
    )
    send_email_task.delay(subject, message, email)


def send_password_reset_email(email: str, token: str) -> None:
    """Send password reset token via email (async via Celery)."""
    subject = "Parolni tiklash — School Device"
    message = (
        f"Parolni tiklash uchun quyidagi kodni kiriting:\n\n"
        f"{token}\n\n"
        f"Agar siz bu so'rovni yubormagan bo'lsangiz, ushbu xabarni e'tiborsiz qoldiring.\n"
        f"Kod 1 soat ichida amal qiladi."
    )
    send_email_task.delay(subject, message, email)
