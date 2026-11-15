"""SAML metadata authorization and outbound network policy regressions."""

import pytest

from app.login import create_access_token
from app.modules.sso import saml_metadata
from app.services import outbound_http
from app.settings import Config
from app.views import sso_admin_view
from tests.factories import create_user


METADATA_URL = "https://example.com/metadata"
METADATA = b'''<?xml version="1.0" encoding="UTF-8"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
                  entityID="https://example.com/idp">
  <IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <KeyDescriptor use="signing">
      <KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">
        <X509Data><X509Certificate>TESTCERT</X509Certificate></X509Data>
      </KeyInfo>
    </KeyDescriptor>
    <SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                        Location="https://example.com/sso"/>
  </IDPSSODescriptor>
</EntityDescriptor>'''


def headers_for(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("authenticated", [False, True])
def test_saml_metadata_requires_admin_before_fetch(client, monkeypatch, authenticated):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", False)
    calls = []
    monkeypatch.setattr(
        sso_admin_view, "parse_saml_idp_metadata",
        lambda url: calls.append(url) or {"metadata_url": url},
    )
    headers = headers_for(create_user()) if authenticated else {}
    response = client.post(
        "/api/admin/sso/saml/metadata/parse", headers=headers,
        json={"metadata_url": METADATA_URL},
    )
    assert response.status_code == 403
    assert calls == []


def test_admin_can_parse_saml_metadata(client, outbound_transport):
    outbound_transport.responses.append((200, {}, METADATA))
    response = client.post(
        "/api/admin/sso/saml/metadata/parse",
        headers=headers_for(create_user(is_admin=True)),
        json={"metadata_url": METADATA_URL},
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "metadata_url": METADATA_URL,
        "saml_idp_entity_id": "https://example.com/idp",
        "saml_idp_sso_url": "https://example.com/sso",
        "saml_idp_slo_url": None,
        "saml_idp_x509_cert": "TESTCERT",
    }
    host, options = outbound_transport.pools[0]
    assert host == "93.184.216.34"
    assert options["assert_hostname"] == "example.com"
    assert options["server_hostname"] == "example.com"
    assert len(outbound_transport.dns_calls) == 1


@pytest.mark.parametrize("payload", [{}, {"metadata_url": 123}, {"metadata_url": ""}])
def test_saml_metadata_invalid_body_returns_400(client, outbound_transport, payload):
    response = client.post(
        "/api/admin/sso/saml/metadata/parse",
        headers=headers_for(create_user(is_admin=True)), json=payload,
    )
    assert response.status_code == 400
    assert outbound_transport.calls == []


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"],
    ["::ffff:127.0.0.1"], ["100.64.0.1"], ["93.184.216.34", "10.0.0.1"],
])
def test_saml_metadata_rejects_nonpublic_dns(outbound_transport, addresses):
    outbound_transport.addresses = addresses
    with pytest.raises(saml_metadata.SamlMetadataError):
        saml_metadata.parse_saml_idp_metadata(METADATA_URL)
    assert outbound_transport.pools == []


@pytest.mark.parametrize("location", ["http://example.com/metadata", "/private"])
def test_saml_metadata_revalidates_redirect(outbound_transport, monkeypatch, location):
    outbound_transport.responses.append((302, {"Location": location}, b""))
    original_resolve = outbound_http.socket.getaddrinfo

    def resolve(host, port, **kwargs):
        if outbound_transport.calls:
            outbound_transport.addresses = ["127.0.0.1"]
        return original_resolve(host, port, **kwargs)

    monkeypatch.setattr(outbound_http.socket, "getaddrinfo", resolve)
    with pytest.raises(saml_metadata.SamlMetadataError):
        saml_metadata.parse_saml_idp_metadata(METADATA_URL)
    assert len(outbound_transport.calls) == 1
    assert len(outbound_transport.dns_calls) == (1 if location.startswith("http:") else 2)


def test_saml_metadata_invalid_json_returns_400(client, outbound_transport):
    response = client.post(
        "/api/admin/sso/saml/metadata/parse",
        headers=headers_for(create_user(is_admin=True)),
        data="{invalid", content_type="application/json",
    )
    assert response.status_code == 400
    assert outbound_transport.calls == []


def test_saml_metadata_allows_admin_approved_private_idp(outbound_transport, monkeypatch):
    outbound_transport.addresses = ["10.0.0.10"]
    outbound_transport.responses.extend([
        (302, {"Location": "/metadata-v2"}, b""), (200, {}, METADATA),
    ])
    monkeypatch.setattr(Config, "OUTBOUND_HTTP_PRIVATE_NETWORK_ALLOWLIST", "10.0.0.0/24")
    result = saml_metadata.parse_saml_idp_metadata(METADATA_URL)
    assert result["saml_idp_x509_cert"] == "TESTCERT"
    assert result["metadata_url"] == METADATA_URL
    assert len(outbound_transport.calls) == 2


@pytest.mark.parametrize("url", [
    "http://example.com/metadata", "https://user:secret@example.com/metadata",
    "https://example.com/metadata#fragment", "https://example.com:invalid/metadata",
    "https://[invalid/metadata",
])
def test_saml_metadata_rejects_unsafe_url_syntax(outbound_transport, url):
    with pytest.raises(saml_metadata.SamlMetadataError) as error:
        saml_metadata.parse_saml_idp_metadata(url)
    assert error.value.code == "sso_saml_metadata_url_invalid"
    assert outbound_transport.calls == []


@pytest.mark.parametrize("status,body", [
    (500, b"sensitive provider response"), (200, b"invalid XML with sensitive details"),
    (200, b"<EntityDescriptor/>"),
])
def test_saml_metadata_errors_do_not_reflect_provider_data(outbound_transport, status, body):
    outbound_transport.responses.append((status, {}, body))
    with pytest.raises(saml_metadata.SamlMetadataError) as error:
        saml_metadata.parse_saml_idp_metadata(METADATA_URL)
    assert "sensitive" not in error.value.message
    assert METADATA_URL not in error.value.message


def test_saml_metadata_bounds_response_and_redirects(outbound_transport, monkeypatch):
    monkeypatch.setattr(Config, "OUTBOUND_HTTP_MAX_RESPONSE_BYTES", 32)
    outbound_transport.responses.append((200, {}, b"x" * 33))
    with pytest.raises(saml_metadata.SamlMetadataError):
        saml_metadata.parse_saml_idp_metadata(METADATA_URL)
    monkeypatch.setattr(Config, "OUTBOUND_HTTP_MAX_REDIRECTS", 1)
    outbound_transport.responses.extend([(302, {"Location": "/loop"}, b"")] * 2)
    with pytest.raises(saml_metadata.SamlMetadataError):
        saml_metadata.parse_saml_idp_metadata(METADATA_URL)
    assert len(outbound_transport.calls) == 3
