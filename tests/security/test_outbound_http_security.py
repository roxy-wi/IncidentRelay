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


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "[::1]", "[::ffff:127.0.0.1]"])
def test_outbound_http_rejects_nonpublic_literal_hosts(outbound_transport, host):
    with pytest.raises(OutboundHttpSecurityError, match="blocked network"):
        resolve_outbound_target(f"https://{host}/push", allow_private_networks=False)
    assert outbound_transport.dns_calls == []


@pytest.mark.parametrize("host", ["2130706433", "0x7f000001", "127.1"])
def test_outbound_http_rejects_alternative_loopback_forms(outbound_transport, host):
    outbound_transport.addresses = ["127.0.0.1"]
    with pytest.raises(OutboundHttpSecurityError, match="blocked network"):
        resolve_outbound_target(f"https://{host}/push", allow_private_networks=False)
    assert len(outbound_transport.dns_calls) == 1


def test_default_outbound_policy_keeps_admin_http_integrations(outbound_transport, monkeypatch):
    from app.services.outbound_http import safe_request
    from app.settings import Config

    monkeypatch.setattr(Config, "OUTBOUND_HTTP_PRIVATE_NETWORK_ALLOWLIST", "10.0.0.0/24")
    outbound_transport.addresses = ["10.0.0.10"]
    outbound_transport.responses.extend([
        (302, {"Location": "/next"}, b""), (200, {}, b"ok"),
    ])
    response = safe_request("GET", "http://example.com/integration")
    assert response.body == b"ok"
    assert len(outbound_transport.calls) == 2
