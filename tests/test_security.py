"""SSRF-protection unit tests."""

import ipaddress
import socket

import pytest

from app.services.security import UnsafeURLError, validate_url


@pytest.fixture()
def fake_dns(monkeypatch):
    """Make DNS resolution deterministic (no real network in unit tests)."""

    def _install(resolved_ip: str):
        def fake_getaddrinfo(host, port, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved_ip, port or 0))]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        return resolved_ip

    return _install


def test_allows_marketplace_domain(fake_dns):
    fake_dns(str(ipaddress.ip_address("93.184.216.34")))
    assert validate_url("https://www.wildberries.ru/catalog/123/detail.aspx")


def test_rejects_non_http_scheme(fake_dns):
    fake_dns("93.184.216.34")
    with pytest.raises(UnsafeURLError):
        validate_url("file:///etc/passwd")
    with pytest.raises(UnsafeURLError):
        validate_url("ftp://wildberries.ru/x.jpg")


def test_rejects_disallowed_domain(fake_dns):
    fake_dns("93.184.216.34")
    with pytest.raises(UnsafeURLError):
        validate_url("https://evil.example.com/image.jpg")


def test_rejects_loopback_ip(fake_dns):
    fake_dns("127.0.0.1")
    with pytest.raises(UnsafeURLError):
        validate_url("https://ozon.ru/product/x")


def test_rejects_private_ip(fake_dns):
    fake_dns("192.168.1.5")
    with pytest.raises(UnsafeURLError):
        validate_url("https://ozon.ru/product/x")


def test_rejects_link_local_metadata_ip(fake_dns):
    fake_dns("169.254.169.254")  # cloud metadata endpoint
    with pytest.raises(UnsafeURLError):
        validate_url("http://169.254.169.254/latest/meta-data/.jpg")


def test_rejects_unresolvable_host(fake_dns, monkeypatch):
    def failing_getaddrinfo(host, port, *args, **kwargs):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
    with pytest.raises(UnsafeURLError):
        validate_url("https://ozon.ru/x.jpg")
