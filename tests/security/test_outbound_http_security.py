import socket

import pytest

from app.services.outbound_http import (
    OutboundHttpSecurityError,
    resolve_outbound_target,
    validate_outbound_url,
)


def test_outbound_http_rejects_loopback_literal():
    with pytest.raises(OutboundHttpSecurityError, match="blocked network"):
        resolve_outbound_target("http://127.0.0.1:8080/internal")


def test_outbound_http_rejects_private_dns_answer(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 443)),
        ],
    )

    with pytest.raises(OutboundHttpSecurityError, match="blocked network"):
        resolve_outbound_target("https://hooks.example.test/notify")


def test_outbound_http_rejects_mixed_public_private_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )

    with pytest.raises(OutboundHttpSecurityError, match="blocked network"):
        resolve_outbound_target("https://hooks.example.test/notify")


def test_outbound_http_rejects_userinfo_credentials():
    with pytest.raises(OutboundHttpSecurityError, match="userinfo"):
        validate_outbound_url("https://user:password@example.com/hook")
