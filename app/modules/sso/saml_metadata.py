from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser

from app.services.outbound_http import (
    OutboundHttpError,
    safe_request,
    validate_outbound_url,
)


class SamlMetadataError(Exception):
    """
    Error raised when SAML IdP metadata cannot be loaded or parsed.
    """

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _validate_metadata_url(metadata_url: str) -> str:
    """
    Validate IdP metadata URL before passing it to python3-saml.
    """
    url = (metadata_url or "").strip()

    if not url:
        raise SamlMetadataError(
            "sso_saml_metadata_url_required",
            "SAML IdP metadata URL is required",
            400,
        )

    try:
        return validate_outbound_url(url, require_https=True)
    except OutboundHttpError as exc:
        raise SamlMetadataError(
            "sso_saml_metadata_url_invalid",
            "SAML IdP metadata URL must be a valid HTTPS URL without credentials or a fragment",
            400,
        ) from exc


def _extract_x509_cert(idp_settings: dict) -> str | None:
    """
    Extract IdP signing certificate from parsed metadata.
    """
    cert = idp_settings.get("x509cert")

    if cert:
        return cert

    cert_multi = idp_settings.get("x509certMulti") or {}
    signing_certs = cert_multi.get("signing") or []

    if signing_certs:
        return signing_certs[0]

    return None


def parse_saml_idp_metadata(metadata_url: str) -> dict:
    """
    Load and parse SAML IdP metadata.
    """
    metadata_url = _validate_metadata_url(metadata_url)

    try:
        response = safe_request(
            "GET", metadata_url, timeout=10, require_https=True,
        )
        response.raise_for_status()
        parsed_metadata = OneLogin_Saml2_IdPMetadataParser.parse(response.body)
    except Exception as exc:
        raise SamlMetadataError(
            "sso_saml_metadata_fetch_failed",
            "Could not fetch or parse SAML IdP metadata",
            400,
        ) from exc

    idp_settings = (parsed_metadata or {}).get("idp") or {}

    entity_id = idp_settings.get("entityId")
    sso_service = idp_settings.get("singleSignOnService") or {}
    slo_service = idp_settings.get("singleLogoutService") or {}

    sso_url = sso_service.get("url")
    slo_url = slo_service.get("url")
    x509_cert = _extract_x509_cert(idp_settings)

    if not entity_id or not sso_url or not x509_cert:
        raise SamlMetadataError(
            "sso_saml_metadata_invalid",
            "SAML IdP metadata must contain entity ID, SSO URL and signing certificate",
            400,
        )

    return {
        "metadata_url": metadata_url,
        "saml_idp_entity_id": entity_id,
        "saml_idp_sso_url": sso_url,
        "saml_idp_slo_url": slo_url,
        "saml_idp_x509_cert": x509_cert,
    }
