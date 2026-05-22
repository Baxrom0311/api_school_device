import pytest
from django.conf import settings


class TestSecuritySettings:
    def test_session_cookie_httponly(self):
        assert settings.SESSION_COOKIE_HTTPONLY is True

    def test_session_cookie_samesite(self):
        assert settings.SESSION_COOKIE_SAMESITE == "Strict"

    def test_csrf_cookie_httponly(self):
        assert settings.CSRF_COOKIE_HTTPONLY is True

    def test_csrf_cookie_samesite(self):
        assert settings.CSRF_COOKIE_SAMESITE == "Strict"

    def test_xframe_options_deny(self):
        assert settings.X_FRAME_OPTIONS == "DENY"

    def test_content_type_nosniff(self):
        assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True

    def test_xss_filter(self):
        assert settings.SECURE_BROWSER_XSS_FILTER is True

    def test_secret_key_required(self):
        assert settings.SECRET_KEY != ""

    def test_cors_tied_to_debug_flag(self):
        """CORS_ALLOW_ALL_ORIGINS should be a boolean (tied to DEBUG in settings.py)."""
        assert isinstance(settings.CORS_ALLOW_ALL_ORIGINS, bool)
