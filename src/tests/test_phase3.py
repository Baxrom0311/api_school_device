"""
Tests for Phase 3 features: holidays, bell logs, monitoring, iCal, panic alerts.
"""
import pytest
from datetime import timedelta, date
from unittest.mock import patch, MagicMock
from django.utils import timezone

from apps.devices.models import Device
from apps.devices.tasks import sync_holidays_to_devices, notify_panic_alert, sync_ical_schedules
from apps.devices.services.ical_parser import parse_ical_to_times


@pytest.mark.django_db
class TestSyncHolidaysToDevices:
    """Test sync_holidays_to_devices task."""

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.publish", return_value=True)
    def test_syncs_holidays(self, mock_publish, device):
        from apps.devices.models.holiday import Holiday

        device.status = "active"
        device.registration_status = "registered"
        device.save()

        today = timezone.now().date()
        Holiday.objects.create(date=today, name="Test Holiday", recurring=False)

        result = sync_holidays_to_devices()

        assert result["synced"] >= 1
        assert result["today_holiday"] is True
        mock_publish.assert_called()

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.publish", return_value=True)
    def test_no_holiday_today(self, mock_publish, device):
        from apps.devices.models.holiday import Holiday

        device.status = "active"
        device.registration_status = "registered"
        device.save()

        # Holiday in the future
        Holiday.objects.create(
            date=date.today() + timedelta(days=30), name="Future", recurring=False
        )

        result = sync_holidays_to_devices()

        assert result["today_holiday"] is False

    @patch("apps.devices.services.mqtt_publisher.MQTTPublisher.publish", return_value=True)
    def test_recurring_holiday_matches_today(self, mock_publish, device):
        from apps.devices.models.holiday import Holiday

        device.status = "active"
        device.registration_status = "registered"
        device.save()

        today = timezone.now().date()
        # Recurring holiday with same month/day but different year
        Holiday.objects.create(
            date=date(2000, today.month, today.day), name="Recurring", recurring=True
        )

        result = sync_holidays_to_devices()

        assert result["today_holiday"] is True


@pytest.mark.django_db
class TestNotifyPanicAlert:
    """Test notify_panic_alert task."""

    def test_skips_when_not_configured(self):
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
            result = notify_panic_alert("DEVICE123", "panic")
            assert result["status"] == "skipped"

    @patch("requests.post")
    def test_sends_telegram(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "123"}):
            result = notify_panic_alert("DEVICE123", "panic")

        assert result["status"] == "sent"
        mock_post.assert_called_once()


@pytest.mark.django_db
class TestSyncIcalSchedules:
    """Test sync_ical_schedules task."""

    @patch("apps.devices.services.url_validator.safe_fetch")
    def test_updates_template_from_ical_url(self, mock_fetch):
        from apps.devices.models.schedule_template import ScheduleTemplate

        ical_content = (
            b"BEGIN:VCALENDAR\r\n"
            b"BEGIN:VEVENT\r\nDTSTART:20240101T083000\r\nEND:VEVENT\r\n"
            b"BEGIN:VEVENT\r\nDTSTART:20240101T093000\r\nEND:VEVENT\r\n"
            b"END:VCALENDAR\r\n"
        )
        mock_fetch.return_value = (ical_content, None)

        template = ScheduleTemplate.objects.create(
            name="iCal Test",
            description="ical:https://example.com/cal.ics",
            times=["07:00"],
        )

        result = sync_ical_schedules()

        assert result["updated"] == 1
        template.refresh_from_db()
        assert "08:30" in template.times
        assert "09:30" in template.times

    def test_skips_templates_without_ical(self):
        from apps.devices.models.schedule_template import ScheduleTemplate

        ScheduleTemplate.objects.create(name="No iCal", description="Just a template", times=["08:00"])

        result = sync_ical_schedules()

        assert result["updated"] == 0

    def test_skips_private_ip_urls(self):
        """SSRF protection: should skip URLs pointing to private IPs."""
        from apps.devices.models.schedule_template import ScheduleTemplate

        ScheduleTemplate.objects.create(
            name="SSRF Test",
            description="ical:https://192.168.1.1/cal.ics",
            times=["08:00"],
        )

        result = sync_ical_schedules()

        assert result["updated"] == 0


class TestValidateIcalUrl:
    """Test URL validation utility (SSRF protection)."""

    def test_allows_valid_https_url(self):
        from apps.devices.services.url_validator import validate_ical_url
        assert validate_ical_url("https://example.com/cal.ics") is None

    def test_rejects_http(self):
        from apps.devices.services.url_validator import validate_ical_url
        assert validate_ical_url("http://example.com/cal.ics") is not None

    def test_rejects_private_ip(self):
        from apps.devices.services.url_validator import validate_ical_url
        assert validate_ical_url("https://192.168.1.1/cal.ics") is not None

    def test_rejects_loopback(self):
        from apps.devices.services.url_validator import validate_ical_url
        assert validate_ical_url("https://127.0.0.1/cal.ics") is not None

    def test_rejects_link_local(self):
        from apps.devices.services.url_validator import validate_ical_url
        assert validate_ical_url("https://169.254.1.1/cal.ics") is not None


class TestParseIcalToTimes:
    """Test iCal parser."""

    def test_parses_dtstart_times(self):
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\nDTSTART:20240101T083000\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nDTSTART:20240101T120000\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        times = parse_ical_to_times(ical)
        assert times == ["08:30", "12:00"]

    def test_deduplicates_times(self):
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\nDTSTART:20240101T083000\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nDTSTART:20240102T083000\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        times = parse_ical_to_times(ical)
        assert times == ["08:30"]

    def test_empty_ical(self):
        assert parse_ical_to_times("") == []

    def test_bytes_input(self):
        ical = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20240101T140000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        times = parse_ical_to_times(ical)
        assert times == ["14:00"]


@pytest.mark.django_db
class TestBellLogFilter:
    """Test BellLog API filtering."""

    def test_filter_by_device(self, admin_client, device):
        from apps.devices.models.bell_log import BellLog

        BellLog.objects.create(device=device, rang_at=timezone.now(), duration_ms=3000, trigger_source="schedule")

        resp = admin_client.get(f"/api/v1/admin/bell-logs/?device={device.id}")
        assert resp.status_code == 200
        assert resp.data["count"] == 1

    def test_filter_by_date_range(self, admin_client, device):
        from apps.devices.models.bell_log import BellLog

        now = timezone.now()
        BellLog.objects.create(device=device, rang_at=now, duration_ms=3000, trigger_source="schedule")
        BellLog.objects.create(
            device=device, rang_at=now - timedelta(days=10), duration_ms=3000, trigger_source="manual"
        )

        # Only last 5 days
        gte = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S")
        resp = admin_client.get(f"/api/v1/admin/bell-logs/?rang_at__gte={gte}")
        assert resp.status_code == 200
        assert resp.data["count"] == 1


@pytest.mark.django_db
class TestHeartbeatMonitoringFields:
    """Test that heartbeat updates rssi, uptime_sec, free_heap."""

    def test_heartbeat_updates_fields(self, device):
        """Simulate what mqtt_listener does on heartbeat."""
        Device.objects.filter(device_id=device.device_id).update(
            last_seen=timezone.now(),
            rssi=-65,
            uptime_sec=3600,
            free_heap=45000,
        )

        device.refresh_from_db()
        assert device.rssi == -65
        assert device.uptime_sec == 3600
        assert device.free_heap == 45000
        assert device.last_seen is not None
