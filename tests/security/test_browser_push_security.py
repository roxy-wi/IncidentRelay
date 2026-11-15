"""Exercise the actual Web Push encryption and outbound transport boundary."""

import base64

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pywebpush import WebPushException

from app.modules.db.models import BrowserPushSubscription
from app.notifiers.browser_push import service as browser_push
from app.services import outbound_http
from tests.factories import create_user


@pytest.fixture
def push_subscription(monkeypatch):
    """Use valid encryption keys so failures cannot hide behind key validation."""
    vapid = Vapid()
    vapid.generate_keys()
    monkeypatch.setattr(browser_push.Config, "BROWSER_PUSH_VAPID_PRIVATE_KEY", vapid)
    monkeypatch.setattr(browser_push.Config, "BROWSER_PUSH_ENABLED", True)
    public_key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint,
    )
    return BrowserPushSubscription.create(
        user=create_user(), endpoint="https://example.com/push/subscription",
        p256dh=base64.urlsafe_b64encode(public_key).decode().rstrip("="),
        auth=base64.urlsafe_b64encode(b"0123456789abcdef").decode().rstrip("="),
    )


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"],
    ["::ffff:127.0.0.1"], ["100.64.0.1"], ["93.184.216.34", "10.0.0.1"],
])
def test_stored_push_endpoint_cannot_reach_private_network(
    push_subscription, outbound_transport, monkeypatch, addresses,
):
    outbound_transport.addresses = addresses
    # Administrative integration exceptions must not apply to user subscriptions.
    monkeypatch.setattr(browser_push.Config, "OUTBOUND_HTTP_PRIVATE_NETWORK_ALLOWLIST", "0.0.0.0/0,::/0")
    unsafe_calls = []

    def unsafe_post(*args, **kwargs):
        unsafe_calls.append(args)
        response = requests.Response()
        response.status_code = 201
        response._content = b""
        return response

    monkeypatch.setattr(requests, "post", unsafe_post)
    with pytest.raises(WebPushException):
        browser_push._webpush(push_subscription, {"body": "private alert"})
    assert outbound_transport.pools == []
    assert unsafe_calls == []


def test_public_push_retains_encryption_vapid_and_pinned_tls(push_subscription, outbound_transport):
    outbound_transport.responses.append((201, {}, b""))
    response = browser_push._webpush(push_subscription, {"body": "private alert"})
    assert response.status_code == 201
    method, path, options = outbound_transport.calls[0]
    assert (method, path) == ("POST", "/push/subscription")
    assert b"private alert" not in options["body"]
    assert len(options["body"]) > 0
    headers = {key.lower(): value for key, value in options["headers"].items()}
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["authorization"].startswith("vapid ")
    assert headers["ttl"] == "0"
    host, pool_options = outbound_transport.pools[0]
    assert host == "93.184.216.34"
    assert pool_options["assert_hostname"] == "example.com"
    assert pool_options["server_hostname"] == "example.com"
    assert pool_options["timeout"].connect_timeout == 10
    assert pool_options["timeout"].read_timeout == 10
    assert len(outbound_transport.dns_calls) == 1


@pytest.mark.parametrize("location", [
    "https://example.com:8443/other-origin", "http://example.com/push", "/redirected",
])
def test_push_does_not_forward_vapid_on_redirect(push_subscription, outbound_transport, location):
    outbound_transport.responses.append((307, {"Location": location}, b""))
    with pytest.raises(WebPushException):
        browser_push._webpush(push_subscription, {"body": "private alert"})
    assert len(outbound_transport.calls) == 1


@pytest.mark.parametrize("status", [404, 410])
def test_push_stale_endpoint_is_disabled(push_subscription, outbound_transport, caplog, status):
    outbound_transport.responses.append((status, {}, b"sensitive provider response"))
    assert browser_push.send_test_push(push_subscription.user) == 0
    push_subscription = BrowserPushSubscription.get_by_id(push_subscription.id)
    assert push_subscription.deleted is True
    assert push_subscription.enabled is False
    assert "sensitive" not in caplog.text


@pytest.mark.parametrize("status", [429, 500])
def test_incident_push_retains_retryable_errors(push_subscription, outbound_transport, status):
    outbound_transport.responses.append((status, {}, b"retry later"))
    with pytest.raises(WebPushException) as error:
        browser_push.send_incident_push_to_subscription(push_subscription, {"body": "alert"})
    assert error.value.response.status_code == status
    assert BrowserPushSubscription.get_by_id(push_subscription.id).deleted is False


def test_push_network_error_is_safe_and_does_not_report_delivery(
    push_subscription, outbound_transport, monkeypatch, caplog,
):
    def fail(*args, **kwargs):
        raise outbound_http.OutboundHttpError("sensitive endpoint or transport details")

    monkeypatch.setattr(outbound_http, "_request_once", fail)
    assert browser_push.send_test_push(push_subscription.user) == 0
    assert "sensitive" not in caplog.text
    assert BrowserPushSubscription.get_by_id(push_subscription.id).deleted is False


def test_disabled_test_push_never_sends(push_subscription, monkeypatch):
    monkeypatch.setattr(browser_push.Config, "BROWSER_PUSH_ENABLED", False)
    monkeypatch.setattr(
        browser_push, "_active_user_subscriptions",
        lambda user_id: pytest.fail("disabled push must not load subscriptions"),
    )
    assert browser_push.send_test_push(push_subscription.user) == 0


def test_push_rechecks_dns_on_later_delivery(push_subscription, outbound_transport):
    outbound_transport.responses.append((201, {}, b""))
    assert browser_push.send_test_push(push_subscription.user) == 1
    outbound_transport.addresses = ["127.0.0.1"]
    assert browser_push.send_test_push(push_subscription.user) == 0
    assert len(outbound_transport.calls) == 1
    assert BrowserPushSubscription.get_by_id(push_subscription.id).deleted is False


@pytest.mark.parametrize("endpoint", [
    "http://example.com/push", "https://user:secret@example.com/push",
    "https://example.com/push#fragment", "https://example.com:invalid/push",
])
def test_push_rejects_unsafe_url_syntax_on_save_and_send(push_subscription, outbound_transport, endpoint):
    with pytest.raises(ValueError):
        browser_push.save_user_subscription(
            push_subscription.user, endpoint,
            keys={"p256dh": push_subscription.p256dh, "auth": push_subscription.auth},
        )
    # Older persisted subscriptions must receive the same validation.
    push_subscription.endpoint = endpoint
    with pytest.raises(WebPushException):
        browser_push._webpush(push_subscription, {"body": "alert"})
    assert outbound_transport.calls == []
