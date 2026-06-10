"""
Tests for forgot password and reset password flows.
"""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestForgotPassword:
    def test_forgot_password_existing_email(self, api_client, regular_user):
        response = api_client.post("/api/v1/auth/forgot-password/", {"email": "user@test.com"})
        assert response.status_code == 200
        # Should not reveal if email exists
        assert "tiklash havolasi yuborildi" in response.data["detail"]

    def test_forgot_password_nonexistent_email(self, api_client, db):
        response = api_client.post("/api/v1/auth/forgot-password/", {"email": "nobody@test.com"})
        assert response.status_code == 200
        # Same response to prevent email enumeration
        assert "tiklash havolasi yuborildi" in response.data["detail"]

    def test_forgot_password_missing_email(self, api_client, db):
        response = api_client.post("/api/v1/auth/forgot-password/", {})
        assert response.status_code == 400

    def test_forgot_password_generates_token(self, api_client, regular_user):
        api_client.post("/api/v1/auth/forgot-password/", {"email": "user@test.com"})
        regular_user.refresh_from_db()
        assert regular_user.password_reset_token is not None
        assert regular_user.password_reset_token_expires is not None


@pytest.mark.django_db
class TestResetPassword:
    def test_reset_password_valid_token(self, api_client, regular_user):
        # Request reset
        api_client.post("/api/v1/auth/forgot-password/", {"email": "user@test.com"})
        regular_user.refresh_from_db()
        token = regular_user.password_reset_token

        # Reset with valid token
        response = api_client.post(
            "/api/v1/auth/reset-password/",
            {
                "email": "user@test.com",
                "token": token,
                "new_password": "newpass123",
            },
        )
        assert response.status_code == 200

        # Verify new password works
        login_resp = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@test.com",
                "password": "newpass123",
            },
        )
        assert login_resp.status_code == 200

    def test_reset_password_invalid_token(self, api_client, regular_user):
        response = api_client.post(
            "/api/v1/auth/reset-password/",
            {
                "email": "user@test.com",
                "token": "invalid_token",
                "new_password": "newpass123",
            },
        )
        assert response.status_code == 400

    def test_reset_password_short_password(self, api_client, regular_user):
        api_client.post("/api/v1/auth/forgot-password/", {"email": "user@test.com"})
        regular_user.refresh_from_db()
        token = regular_user.password_reset_token

        response = api_client.post(
            "/api/v1/auth/reset-password/",
            {
                "email": "user@test.com",
                "token": token,
                "new_password": "short",
            },
        )
        assert response.status_code == 400

    def test_reset_password_missing_fields(self, api_client, db):
        response = api_client.post("/api/v1/auth/reset-password/", {"email": "user@test.com"})
        assert response.status_code == 400

    def test_reset_password_clears_token(self, api_client, regular_user):
        api_client.post("/api/v1/auth/forgot-password/", {"email": "user@test.com"})
        regular_user.refresh_from_db()
        token = regular_user.password_reset_token

        api_client.post(
            "/api/v1/auth/reset-password/",
            {
                "email": "user@test.com",
                "token": token,
                "new_password": "newpass123",
            },
        )

        regular_user.refresh_from_db()
        assert regular_user.password_reset_token is None

        # Token can't be reused
        response = api_client.post(
            "/api/v1/auth/reset-password/",
            {
                "email": "user@test.com",
                "token": token,
                "new_password": "anotherpass",
            },
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestResetPasswordExpiredToken:
    def test_expired_token_rejected(self, api_client, regular_user):
        from datetime import timedelta

        from django.utils import timezone

        # Set an expired token directly
        regular_user.password_reset_token = "expired-token-123"
        regular_user.password_reset_token_expires = timezone.now() - timedelta(hours=1)
        regular_user.save(update_fields=["password_reset_token", "password_reset_token_expires"])

        response = api_client.post(
            "/api/v1/auth/reset-password/",
            {
                "email": "user@test.com",
                "token": "expired-token-123",
                "new_password": "newpass123",
            },
        )
        assert response.status_code == 400
        assert "muddati tugagan" in response.data["detail"]


@pytest.mark.django_db
class TestForgotPasswordRateLimit:
    """Verify throttle scopes are configured on forgot/reset password views."""

    def test_forgot_password_has_throttle_scope(self):
        from rest_framework.throttling import ScopedRateThrottle

        from apps.users.api.v1.views.forgot_password import ForgotPasswordView

        assert ScopedRateThrottle in ForgotPasswordView.throttle_classes
        assert ForgotPasswordView.throttle_scope == "forgot_password"

    def test_reset_password_has_throttle_scope(self):
        from rest_framework.throttling import ScopedRateThrottle

        from apps.users.api.v1.views.forgot_password import ResetPasswordView

        assert ScopedRateThrottle in ResetPasswordView.throttle_classes
        assert ResetPasswordView.throttle_scope == "reset_password"

    def test_throttle_rates_configured(self):
        from core.config.rest_framework import REST_FRAMEWORK

        rates = REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        assert "forgot_password" in rates
        assert "reset_password" in rates
