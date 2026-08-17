"""SSRF-resistant HTTP client for administrator-configured outbound integrations."""

from __future__ import annotations

import ipaddress
import json as jsonlib
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit

import urllib3

from app.settings import Config


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class OutboundHttpError(RuntimeError):
    """Base error for a bounded outbound HTTP request."""


class OutboundHttpSecurityError(OutboundHttpError):
    """Raised when a destination violates the outbound network policy."""


@dataclass(frozen=True)
class OutboundHttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]
    url: str

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return jsonlib.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OutboundHttpError(
                f"outbound HTTP request returned status {self.status_code}"
            )


def validate_outbound_url(url: str) -> str:
    """Validate URL syntax without making a network request."""
    value = str(url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise OutboundHttpSecurityError("outbound URL must use http or https")
    if not parsed.hostname:
        raise OutboundHttpSecurityError("outbound URL requires a hostname")
    if parsed.username or parsed.password:
        raise OutboundHttpSecurityError("outbound URL must not contain userinfo credentials")
    if parsed.fragment:
        raise OutboundHttpSecurityError("outbound URL must not contain a fragment")
    return value


def _allowlist_networks() -> Sequence[Any]:
    raw = str(
        getattr(Config, "OUTBOUND_HTTP_PRIVATE_NETWORK_ALLOWLIST", "") or ""
    )
    networks = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise OutboundHttpSecurityError(
                "invalid outbound private-network allowlist"
            ) from exc
    return tuple(networks)


def _address_allowed(address: ipaddress._BaseAddress) -> bool:
    unsafe = (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
    if not unsafe:
        return True
    return any(address in network for network in _allowlist_networks())


def resolve_outbound_target(url: str):
    """Resolve every address, enforce policy, and pin one approved target IP."""
    value = validate_outbound_url(url)
    parsed = urlsplit(value)
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)

    try:
        addresses = [ipaddress.ip_address(parsed.hostname)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise OutboundHttpError("outbound hostname resolution failed") from exc

        addresses = []
        for info in infos:
            try:
                address = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)

    if not addresses:
        raise OutboundHttpError("outbound hostname resolved to no addresses")

    # Fail closed if DNS returns even one prohibited address. This prevents an
    # attacker from mixing a public answer with loopback/private answers.
    if not all(_address_allowed(address) for address in addresses):
        raise OutboundHttpSecurityError(
            "outbound target resolves to a blocked network"
        )

    return parsed, str(addresses[0]), port


def _host_header(parsed) -> str:
    host = parsed.hostname or ""
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    if parsed.port and parsed.port != default_port:
        return f"{host}:{parsed.port}"
    return host


def _request_once(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: int | float,
):
    parsed, target_ip, port = resolve_outbound_target(url)
    request_headers = {str(k): str(v) for k, v in dict(headers or {}).items()}
    request_headers.pop("Host", None)
    request_headers.pop("host", None)
    request_headers["Host"] = _host_header(parsed)
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    bounded_timeout = urllib3.Timeout(connect=timeout, read=timeout)

    if parsed.scheme.lower() == "https":
        pool = urllib3.HTTPSConnectionPool(
            target_ip,
            port=port,
            timeout=bounded_timeout,
            maxsize=1,
            block=True,
            retries=False,
            cert_reqs=ssl.CERT_REQUIRED,
            assert_hostname=parsed.hostname,
            server_hostname=parsed.hostname,
        )
    else:
        pool = urllib3.HTTPConnectionPool(
            target_ip,
            port=port,
            timeout=bounded_timeout,
            maxsize=1,
            block=True,
            retries=False,
        )

    response = None
    try:
        response = pool.urlopen(
            method.upper(),
            path,
            body=body,
            headers=request_headers,
            redirect=False,
            retries=False,
            preload_content=False,
        )
        limit = int(getattr(Config, "OUTBOUND_HTTP_MAX_RESPONSE_BYTES", 1048576))
        payload = response.read(amt=limit + 1, decode_content=True)
        if len(payload) > limit:
            raise OutboundHttpError("outbound HTTP response exceeded size limit")
        return int(response.status), dict(response.headers), payload
    except (OutboundHttpError, OutboundHttpSecurityError):
        raise
    except Exception as exc:
        raise OutboundHttpError(
            f"outbound HTTP request failed: {exc.__class__.__name__}"
        ) from exc
    finally:
        if response is not None:
            response.release_conn()
        pool.close()


def safe_request(
    method: str,
    url: str,
    *,
    json: Any = None,
    data: bytes | str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: int | float = 10,
) -> OutboundHttpResponse:
    """Perform a DNS-pinned request and re-check every redirect target."""
    current_url = validate_outbound_url(url)
    current_method = str(method or "GET").upper()
    request_headers = dict(headers or {})

    if json is not None:
        body = jsonlib.dumps(
            json,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif isinstance(data, str):
        body = data.encode("utf-8")
    else:
        body = data

    max_redirects = int(getattr(Config, "OUTBOUND_HTTP_MAX_REDIRECTS", 3))
    for redirect_count in range(max_redirects + 1):
        status, response_headers, response_body = _request_once(
            current_method,
            current_url,
            headers=request_headers,
            body=body,
            timeout=timeout,
        )
        if status not in _REDIRECT_STATUSES:
            return OutboundHttpResponse(
                status_code=status,
                body=response_body,
                headers=response_headers,
                url=current_url,
            )

        location = response_headers.get("Location") or response_headers.get("location")
        if not location:
            return OutboundHttpResponse(status, response_body, response_headers, current_url)
        if redirect_count >= max_redirects:
            raise OutboundHttpSecurityError("outbound redirect limit exceeded")

        current_url = validate_outbound_url(urljoin(current_url, location))
        if status == 303:
            current_method = "GET"
            body = None

    raise OutboundHttpSecurityError("outbound redirect limit exceeded")


__all__ = [
    "OutboundHttpError",
    "OutboundHttpResponse",
    "OutboundHttpSecurityError",
    "resolve_outbound_target",
    "safe_request",
    "validate_outbound_url",
]
