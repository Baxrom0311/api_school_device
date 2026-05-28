"""Tests for SSRF-hardened URL validator."""
import pytest
from unittest.mock import patch, MagicMock

from apps.devices.services.url_validator import validate_ical_url, _is_ip_blocked, safe_fetch


class TestIsIpBlocked:
    def test_private_10_blocked(self):
        assert _is_ip_blocked("10.0.0.1") is True

    def test_private_172_blocked(self):
        assert _is_ip_blocked("172.16.0.1") is True

    def test_private_192_blocked(self):
        assert _is_ip_blocked("192.168.1.1") is True

    def test_loopback_blocked(self):
        assert _is_ip_blocked("127.0.0.1") is True

    def test_link_local_blocked(self):
        assert _is_ip_blocked("169.254.1.1") is True

    def test_ipv6_loopback_blocked(self):
        assert _is_ip_blocked("::1") is True

    def test_public_ip_allowed(self):
        assert _is_ip_blocked("8.8.8.8") is False

    def test_cgn_blocked(self):
        assert _is_ip_blocked("100.64.0.1") is True


class TestValidateIcalUrl:
    def test_http_rejected(self):
        assert validate_ical_url("http://example.com/cal.ics") == "Only HTTPS URLs are allowed"

    def test_private_ip_rejected(self):
        assert validate_ical_url("https://192.168.1.1/cal.ics") is not None

    def test_loopback_ip_rejected(self):
        assert validate_ical_url("https://127.0.0.1/cal.ics") is not None

    def test_no_hostname_rejected(self):
        assert validate_ical_url("https:///path") is not None

    @patch("apps.devices.services.url_validator.socket.getaddrinfo")
    def test_dns_resolving_to_private_rejected(self, mock_dns):
        mock_dns.return_value = [(2, 1, 0, "", ("10.0.0.1", 443))]
        result = validate_ical_url("https://evil.com/cal.ics")
        assert result is not None
        assert "blocked" in result

    @patch("apps.devices.services.url_validator.socket.getaddrinfo")
    def test_dns_resolving_to_public_allowed(self, mock_dns):
        mock_dns.return_value = [(2, 1, 0, "", ("93.184.216.34", 443))]
        result = validate_ical_url("https://example.com/cal.ics")
        assert result is None


class TestSafeFetch:
    @patch("apps.devices.services.url_validator.socket.getaddrinfo")
    @patch("requests.Session.get")
    def test_pins_connection_to_resolved_ip(self, mock_get, mock_dns):
        """Verify safe_fetch connects to the resolved IP, not re-resolving DNS."""
        mock_dns.return_value = [(2, 1, 0, "", ("93.184.216.34", 443))]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_redirect = False
        mock_resp.content = b"calendar data"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        content, error = safe_fetch("https://example.com/cal.ics")

        assert error is None
        assert content == b"calendar data"
        # Verify the URL was rewritten to use the resolved IP
        call_url = mock_get.call_args[0][0]
        assert "93.184.216.34" in call_url
        # Verify Host header is set to original hostname
        call_headers = mock_get.call_args[1]["headers"]
        assert call_headers["Host"] == "example.com"

    @patch("apps.devices.services.url_validator.socket.getaddrinfo")
    @patch("requests.Session.get")
    def test_blocks_redirect(self, mock_get, mock_dns):
        mock_dns.return_value = [(2, 1, 0, "", ("93.184.216.34", 443))]
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.is_redirect = True
        mock_get.return_value = mock_resp

        content, error = safe_fetch("https://example.com/cal.ics")
        assert content is None
        assert "Redirect" in error

    def test_blocks_private_ip(self):
        content, error = safe_fetch("https://192.168.1.1/cal.ics")
        assert content is None
        assert error is not None

    def test_blocks_http(self):
        content, error = safe_fetch("http://example.com/cal.ics")
        assert content is None
        assert "HTTPS" in error

    @patch("apps.devices.services.url_validator.socket.getaddrinfo")
    def test_blocks_dns_rebinding_to_private(self, mock_dns):
        """DNS resolving to private IP should be blocked even with valid hostname."""
        mock_dns.return_value = [(2, 1, 0, "", ("127.0.0.1", 443))]
        content, error = safe_fetch("https://evil.com/cal.ics")
        assert content is None
        assert "blocked" in error
