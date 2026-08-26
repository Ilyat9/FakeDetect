"""SSRF-safe HTTP utilities.

All outbound requests that use a user-supplied URL MUST go through
``validate_url`` / ``safe_get`` instead of a raw ``httpx.AsyncClient.get``,
so that internal network addresses and non-marketplace hosts are rejected.
"""

import ipaddress
import logging
import socket
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Whitelist of allowed domain suffixes (marketplaces + their CDNs).
ALLOWED_DOMAIN_SUFFIXES = (
    "wildberries.ru",
    "wbbasket.ru",
    "wbstatic.net",
    "ozon.ru",
    "ozonusercontent.com",
    "ozone.ru",
    "market.yandex.ru",
    "yandex.net",
    "yandex.ru",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MAX_CONTENT_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT = 15.0


class UnsafeURLError(ValueError):
    """Raised when a URL fails SSRF validation."""


def _is_allowed_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAIN_SUFFIXES)


def _validate_resolved_ips(host: str) -> None:
    """Resolve DNS and reject private/loopback/link-local/reserved addresses."""
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Cannot resolve host '{host}': {e}")

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeURLError(
                f"Host '{host}' resolves to a forbidden address ({ip})"
            )


def validate_url(url: str) -> str:
    """Validate scheme, whitelist the host and check resolved IPs.

    Returns the normalized URL string, raises UnsafeURLError otherwise.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Only http/https schemes are allowed: {url}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError(f"URL has no hostname: {url}")
    if not _is_allowed_host(host):
        raise UnsafeURLError(f"Domain '{host}' is not in the allowed list")

    _validate_resolved_ips(host)
    return url.strip()


async def safe_get(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_size: int = MAX_CONTENT_SIZE,
) -> httpx.Response:
    """Perform an SSRF-validated GET request.

    - Validates the initial URL against the domain whitelist and DNS checks.
    - Follows redirects manually, re-validating every hop.
    - Enforces a maximum download size.
    """
    current_url = validate_url(url)
    default_headers = {"User-Agent": USER_AGENT}
    if headers:
        default_headers.update(headers)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            response = await client.get(current_url, headers=default_headers)
            if response.is_redirect:
                location = response.headers.get("location", "")
                if not location:
                    raise httpx.HTTPError(f"Redirect without Location header from {current_url}")
                # Resolve relative redirects against the current URL, then re-validate.
                current_url = validate_url(str(httpx.URL(current_url).join(location)))
                continue
            break

        if response.status_code >= 400:
            return response

        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_size:
            raise httpx.HTTPError(f"Response too large (> {max_size} bytes): {current_url}")

        await response.aread()
        if len(response.content) > max_size:
            raise httpx.HTTPError(f"Response too large (> {max_size} bytes): {current_url}")
        return response
