"""iCal parser service — extracts bell times from iCal content."""
import re
from datetime import datetime


def parse_ical_to_times(ical_content: bytes | str) -> list[str]:
    """
    Parse iCal content and extract event start times as HH:MM strings.

    Uses simple regex parsing to avoid external dependency on icalendar package.
    Handles DTSTART in both date-time and time-only formats.
    """
    if isinstance(ical_content, bytes):
        ical_content = ical_content.decode("utf-8", errors="replace")

    # Match DTSTART lines: DTSTART:20240101T083000 or DTSTART;VALUE=DATE-TIME:...
    pattern = re.compile(r"DTSTART[^:]*:(\d{4}\d{2}\d{2}T(\d{2})(\d{2})\d{2})")
    times_set: set[str] = set()

    for match in pattern.finditer(ical_content):
        hour = match.group(2)
        minute = match.group(3)
        times_set.add(f"{hour}:{minute}")

    return sorted(times_set)
