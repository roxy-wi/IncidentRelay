"""Cloud.ru Advanced Simple Message Notification verification helpers."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlparse

import requests
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import padding, rsa


SMN_MESSAGE_TYPES = {
    "Notification",
    "SubscriptionConfirmation",
    "UnsubscribeConfirmation",
}


class CloudRuSmnError(Exception):
    """Safe error returned while processing a Cloud.ru SMN message."""

    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _validated_cloud_ru_url(url, *, purpose):
    try:
        parsed = urlparse(str(url or "").strip())
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise CloudRuSmnError(
            f"cloud_ru_smn_invalid_{purpose}_url",
            f"Cloud.ru SMN {purpose} URL is invalid.",
            403,
        ) from exc

    host = (parsed.hostname or "").rstrip(".").lower()

    if parsed.scheme != "https":
        raise CloudRuSmnError(
            f"cloud_ru_smn_invalid_{purpose}_url",
            f"Cloud.ru SMN {purpose} URL must use HTTPS.",
            403,
        )

    # Cloud.ru SMN documentation requires certificate-server identity
    # validation. Restrict all provider-controlled callback URLs to Cloud.ru
    # DNS names so a signed message cannot turn IncidentRelay into an SSRF
    # client for an arbitrary host.
    if host != "cloud.ru" and not host.endswith(".cloud.ru"):
        raise CloudRuSmnError(
            f"cloud_ru_smn_invalid_{purpose}_url",
            f"Cloud.ru SMN {purpose} URL host is not allowed.",
            403,
        )

    if parsed.username or parsed.password:
        raise CloudRuSmnError(
            f"cloud_ru_smn_invalid_{purpose}_url",
            f"Cloud.ru SMN {purpose} URL must not contain credentials.",
            403,
        )

    if port not in {None, 443}:
        raise CloudRuSmnError(
            f"cloud_ru_smn_invalid_{purpose}_url",
            f"Cloud.ru SMN {purpose} URL uses an invalid port.",
            403,
        )

    return parsed


def validate_cloud_ru_signing_cert_url(url):
    parsed = _validated_cloud_ru_url(url, purpose="certificate")
    if parsed.query or parsed.fragment:
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_certificate_url",
            "Cloud.ru SMN certificate URL is invalid.",
            403,
        )
    if not parsed.path.lower().endswith(".pem"):
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_certificate_url",
            "Cloud.ru SMN certificate URL must reference a PEM certificate.",
            403,
        )
    return parsed


@lru_cache(maxsize=32)
def _load_signing_certificate(url):
    validate_cloud_ru_signing_cert_url(url)

    try:
        response = requests.get(url, timeout=10, allow_redirects=False)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CloudRuSmnError(
            "cloud_ru_smn_certificate_unavailable",
            "Cloud.ru SMN signing certificate could not be loaded.",
            502,
        ) from exc

    if len(response.content) > 128 * 1024:
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_certificate",
            "Cloud.ru SMN signing certificate is too large.",
            403,
        )

    try:
        certificate = x509.load_pem_x509_certificate(response.content)
    except ValueError as exc:
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_certificate",
            "Cloud.ru SMN signing certificate is invalid.",
            403,
        ) from exc

    now = datetime.now(timezone.utc)
    not_before = getattr(
        certificate,
        "not_valid_before_utc",
        certificate.not_valid_before.replace(tzinfo=timezone.utc),
    )
    not_after = getattr(
        certificate,
        "not_valid_after_utc",
        certificate.not_valid_after.replace(tzinfo=timezone.utc),
    )
    if now < not_before or now > not_after:
        raise CloudRuSmnError(
            "cloud_ru_smn_expired_certificate",
            "Cloud.ru SMN signing certificate is not valid.",
            403,
        )

    if not isinstance(certificate.public_key(), rsa.RSAPublicKey):
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_certificate",
            "Cloud.ru SMN signing certificate must contain an RSA public key.",
            403,
        )

    return certificate


def build_cloud_ru_smn_signing_string(envelope):
    """Build the canonical SMN V1 signing string documented by Cloud.ru."""
    message_type = envelope.get("type")

    if message_type == "Notification":
        field_names = ["message", "message_id"]
        if envelope.get("subject") is not None:
            field_names.append("subject")
        field_names.extend(["timestamp", "topic_urn", "type"])
    elif message_type in {"SubscriptionConfirmation", "UnsubscribeConfirmation"}:
        field_names = [
            "message",
            "message_id",
            "subscribe_url",
            "timestamp",
            "topic_urn",
            "type",
        ]
    else:
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_type",
            "Unsupported Cloud.ru SMN message type.",
            400,
        )

    parts = []
    for field_name in field_names:
        value = envelope.get(field_name)
        if value is None:
            raise CloudRuSmnError(
                "cloud_ru_smn_missing_signature_field",
                f"Cloud.ru SMN message is missing the signed field {field_name}.",
                400,
            )
        parts.extend([field_name, str(value)])

    return "".join(f"{part}\n" for part in parts)


def validate_cloud_ru_smn_message(envelope, expected_topic_urn):
    """Verify Cloud.ru SMN topic identity and RSA V1 signature."""
    message_type = envelope.get("type")
    if message_type not in SMN_MESSAGE_TYPES:
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_type",
            "Unsupported Cloud.ru SMN message type.",
            400,
        )

    topic_urn = str(envelope.get("topic_urn") or "").strip()
    if not expected_topic_urn:
        raise CloudRuSmnError(
            "cloud_ru_smn_topic_not_configured",
            "Cloud.ru SMN Topic URN is not configured for this route.",
            400,
        )
    if topic_urn != expected_topic_urn:
        raise CloudRuSmnError(
            "cloud_ru_smn_topic_mismatch",
            "Cloud.ru SMN Topic URN does not match this route.",
            403,
        )

    if str(envelope.get("signature_version") or "").lower() != "v1":
        raise CloudRuSmnError(
            "cloud_ru_smn_signature_version_unsupported",
            "Cloud.ru SMN signature version is not supported.",
            400,
        )

    certificate = _load_signing_certificate(envelope.get("signing_cert_url"))
    digest = certificate.signature_hash_algorithm
    if digest is None:
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_certificate",
            "Cloud.ru SMN certificate signature algorithm is unavailable.",
            403,
        )

    try:
        signature = base64.b64decode(envelope.get("signature") or "", validate=True)
    except (ValueError, TypeError) as exc:
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_signature",
            "Cloud.ru SMN signature is invalid.",
            403,
        ) from exc

    try:
        certificate.public_key().verify(
            signature,
            build_cloud_ru_smn_signing_string(envelope).encode("utf-8"),
            padding.PKCS1v15(),
            digest,
        )
    except InvalidSignature as exc:
        raise CloudRuSmnError(
            "cloud_ru_smn_invalid_signature",
            "Cloud.ru SMN signature verification failed.",
            403,
        ) from exc

    return True


def confirm_cloud_ru_smn_subscription(subscribe_url):
    """Confirm a signed Cloud.ru SMN HTTP/HTTPS subscription."""
    _validated_cloud_ru_url(subscribe_url, purpose="confirmation")
    try:
        response = requests.get(subscribe_url, timeout=10, allow_redirects=False)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CloudRuSmnError(
            "cloud_ru_smn_confirmation_failed",
            "Cloud.ru SMN subscription confirmation failed.",
            502,
        ) from exc
    return True
