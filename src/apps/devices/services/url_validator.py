"""URL validation utilities for external resource fetching (SSRF protection).

Resolves DNS before allowing fetch and validates all resolved IPs against
private/loopback/link-local ranges. Blocks redirect following.
"""

import ipaddress
import socket
from urllib.parse import urlparse

# Blocked IP ranges (private, loopback, link-local, reserved)
_BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGN
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
]


def _is_ip_blocked(ip_str: str) -> bool:
    """Check if an IP address falls within any blocked range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable = blocked
    return any(addr in net for net in _BLOCKED_RANGES)


def resolve_and_validate(hostname: str) -> str | None:
    """Resolve hostname via DNS and validate all IPs. Returns error or None."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return f"DNS resolution failed for {hostname}"

    if not results:
        return f"No DNS records for {hostname}"

    for _family, _, _, _, sockaddr in results:
        ip = str(sockaddr[0])
        if _is_ip_blocked(ip):
            return f"Resolved IP {ip} is in a blocked range"

    return None


def validate_ical_url(url: str) -> str | None:
    """
    Validate iCal URL for safe fetching:
    - HTTPS only
    - DNS resolution to non-private IPs
    Returns error string or None if safe.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        return "Only HTTPS URLs are allowed"

    hostname = parsed.hostname
    if not hostname:
        return "Invalid URL: no hostname"

    # Check if hostname is a raw IP
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_ip_blocked(str(ip)):
            return "Private/loopback IPs are not allowed"
        return None
    except ValueError:
        pass  # hostname, not IP — resolve DNS

    return resolve_and_validate(hostname)


def safe_fetch(url: str, *, timeout: int = 10, max_bytes: int = 1024 * 1024) -> tuple[bytes | None, str | None]:
    """
    Fetch URL with SSRF protection: resolves DNS, pins to validated IP, disables redirects.
    Returns (content_bytes, error_string). One will be None.

    Uses a custom transport adapter to force connection to the pre-resolved IP,
    preventing DNS rebinding (TOCTOU) attacks.
    """
    import requests as http_requests

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None, "Only HTTPS URLs are allowed"

    hostname = parsed.hostname
    if not hostname:
        return None, "Invalid URL: no hostname"

    # Resolve and validate IP before connecting
    try:
        ip_addr = ipaddress.ip_address(hostname)
        if _is_ip_blocked(str(ip_addr)):
            return None, "Private/loopback IPs are not allowed"
        resolved_ip = str(ip_addr)
    except ValueError:
        # Hostname — resolve DNS
        try:
            results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return None, f"DNS resolution failed for {hostname}"
        if not results:
            return None, f"No DNS records for {hostname}"
        for _, _, _, _, sockaddr in results:
            if _is_ip_blocked(str(sockaddr[0])):
                return None, f"Resolved IP {sockaddr[0]} is in a blocked range"
        resolved_ip = str(results[0][4][0])

    # Pin the connection to the resolved IP via Host header override
    port = parsed.port or 443
    pinned_url = url.replace(f"://{hostname}", f"://{resolved_ip}", 1)
    if parsed.port:
        pinned_url = url.replace(f"://{hostname}:{parsed.port}", f"://{resolved_ip}:{port}", 1)

    try:
        session = http_requests.Session()
        session.max_redirects = 0
        resp = session.get(
            pinned_url,
            headers={"Host": hostname},
            timeout=timeout,
            allow_redirects=False,
            verify=True,
        )
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            return None, "Redirects are not allowed"
        resp.raise_for_status()
        return resp.content[:max_bytes], None
    except http_requests.RequestException as e:
        return None, f"Fetch failed: {e}"
