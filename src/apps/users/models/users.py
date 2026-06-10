from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.tokens import RefreshToken

from apps.shared.models.base import AbstractBaseModel
from apps.users.managers.users import UserManager


class RoleChoices(models.TextChoices):
    ADMIN = "ADMIN", _("Admin")
    SCHOOL_ADMIN = "SCHOOL_ADMIN", _("School Admin")
    USER = "USER", _("User")


class User(AbstractUser, AbstractBaseModel):
    email = models.EmailField(
        verbose_name=_("Email"),
        unique=True,
        db_index=True,
    )
    username = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("Username"),
        db_index=True,
    )
    avatar = models.ImageField(
        upload_to="avatars/",
        null=True,
        blank=True,
        verbose_name=_("Avatar"),
    )
    role = models.CharField(
        choices=RoleChoices.choices,
        max_length=20,
        default=RoleChoices.USER,
        verbose_name=_("Role"),
    )

    # Registration & Verification fields
    organization_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Organization Name"),
        help_text=_("School or organization name"),
    )
    is_verified = models.BooleanField(
        default=False,
        verbose_name=_("Email Verified"),
        help_text=_("Whether the user's email has been verified"),
    )
    verification_token = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Verification Token"),
        help_text=_("Token for email verification"),
    )
    verification_token_expires = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Token Expires"),
        help_text=_("When the verification token expires"),
    )
    password_reset_token = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Password Reset Token"),
        help_text=_("Token for password reset"),
    )
    password_reset_token_expires = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Reset Token Expires"),
        help_text=_("When the password reset token expires"),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects: ClassVar[UserManager] = UserManager()

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} - {self.email}" if self.email else str(_("User"))

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["-created_at"]
        db_table = "users"

    def tokens(self) -> dict[str, str | int]:
        refresh = RefreshToken.for_user(self)
        return {
            "access": str(refresh.access_token),  # type:ignore
            "refresh": str(refresh),
            "user": str(self.id),
        }

    def generate_verification_token(self) -> str:
        """Generate a new email verification token"""
        import secrets
        from datetime import timedelta

        from django.utils import timezone

        self.verification_token = secrets.token_urlsafe(32)
        self.verification_token_expires = timezone.now() + timedelta(hours=24)
        self.save(update_fields=["verification_token", "verification_token_expires"])
        return self.verification_token

    def verify_email(self, token: str) -> bool:
        """Verify email with token"""
        from django.utils import timezone

        if not self.verification_token or self.verification_token != token:
            return False

        if self.verification_token_expires and self.verification_token_expires < timezone.now():
            return False

        self.is_verified = True
        self.verification_token = None
        self.verification_token_expires = None
        self.save(update_fields=["is_verified", "verification_token", "verification_token_expires"])
        return True

    def resend_verification_token(self) -> str:
        """Resend verification email with new token"""
        return self.generate_verification_token()
