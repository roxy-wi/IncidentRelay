"""Network-boundary fixtures for outbound request security regressions."""

import socket
from types import SimpleNamespace

import pytest

from app.services import outbound_http


@pytest.fixture
def outbound_transport(monkeypatch):
    """Keep DNS and sockets local while exercising the real outbound client."""
    transport = SimpleNamespace(
        addresses=["93.184.216.34"], responses=[], calls=[], pools=[], dns_calls=[],
    )

    def resolve(host, port, **kwargs):
        transport.dns_calls.append((host, port))
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in transport.addresses
        ]

    class Pool:
        def __init__(self, host, **kwargs):
            transport.pools.append((host, kwargs))

        def urlopen(self, method, path, **kwargs):
            transport.calls.append((method, path, kwargs))
            status, headers, body = transport.responses.pop(0)
            return SimpleNamespace(
                status=status, headers=headers,
                read=lambda amt, **kwargs: body[:amt],
                release_conn=lambda: None,
            )

        def close(self):
            pass

    monkeypatch.setattr(outbound_http.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(outbound_http.urllib3, "HTTPSConnectionPool", Pool)
    monkeypatch.setattr(outbound_http.urllib3, "HTTPConnectionPool", Pool)
    monkeypatch.setattr(outbound_http.Config, "OUTBOUND_HTTP_PRIVATE_NETWORK_ALLOWLIST", "")
    return transport
