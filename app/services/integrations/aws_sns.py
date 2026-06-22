import base64
import re
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import parse_qs, urlparse

import requests
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding


SNS_CERT_HOST_PATTERN = re.compile(
    r"^sns(?:\.[a-z0-9-]+)?\.amazonaws\.com(?:\.cn)?$"
)

SNS_CERT_PATH_PATTERN = re.compile(
    r"^/SimpleNotificationService-[A-Za-z0-9_-]+\.pem$"
)

SNS_MESSAGE_TYPES = {
    "Notification",
    "SubscriptionConfirmation",
    "UnsubscribeConfirmation",
}


class AwsSnsError(Exception):
    """Safe error returned while processing an SNS message."""

    def __init__(
        self,
        code,
        message,
        status_code=400,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _validated_url_parts(url):
    try:
        parsed = urlparse(str(url or "").strip())
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise AwsSnsError(
            "aws_sns_invalid_url",
            "Amazon SNS URL is invalid.",
            403,
        ) from exc

    host = (parsed.hostname or "").lower()

    if parsed.scheme != "https":
        raise AwsSnsError(
            "aws_sns_invalid_url",
            "Amazon SNS URL must use HTTPS.",
            403,
        )

    if not SNS_CERT_HOST_PATTERN.fullmatch(host):
        raise AwsSnsError(
            "aws_sns_invalid_url",
            "Amazon SNS URL host is not allowed.",
            403,
        )

    if parsed.username or parsed.password:
        raise AwsSnsError(
            "aws_sns_invalid_url",
            "Amazon SNS URL must not contain credentials.",
            403,
        )

    if port not in {None, 443}:
        raise AwsSnsError(
            "aws_sns_invalid_url",
            "Amazon SNS URL uses an invalid port.",
            403,
        )

    return parsed


def validate_signing_cert_url(url):
    """Reject non-AWS certificate URLs before any network request."""
    parsed = _validated_url_parts(url)

    if parsed.query or parsed.fragment:
        raise AwsSnsError(
            "aws_sns_invalid_certificate_url",
            "Amazon SNS certificate URL is invalid.",
            403,
        )

    if not SNS_CERT_PATH_PATTERN.fullmatch(parsed.path):
        raise AwsSnsError(
            "aws_sns_invalid_certificate_url",
            "Amazon SNS certificate path is invalid.",
            403,
        )

    return parsed


@lru_cache(maxsize=32)
def _load_signing_certificate(url):
    validate_signing_cert_url(url)

    try:
        response = requests.get(
            url,
            timeout=10,
            allow_redirects=False,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AwsSnsError(
            "aws_sns_certificate_unavailable",
            "Amazon SNS signing certificate could not be loaded.",
            502,
        ) from exc

    if len(response.content) > 128 * 1024:
        raise AwsSnsError(
            "aws_sns_invalid_certificate",
            "Amazon SNS signing certificate is too large.",
            403,
        )

    try:
        certificate = x509.load_pem_x509_certificate(
            response.content
        )
    except ValueError as exc:
        raise AwsSnsError(
            "aws_sns_invalid_certificate",
            "Amazon SNS signing certificate is invalid.",
            403,
        ) from exc

    now = datetime.now(timezone.utc)

    not_before = getattr(
        certificate,
        "not_valid_before_utc",
        certificate.not_valid_before.replace(
            tzinfo=timezone.utc
        ),
    )
    not_after = getattr(
        certificate,
        "not_valid_after_utc",
        certificate.not_valid_after.replace(
            tzinfo=timezone.utc
        ),
    )

    if now < not_before or now > not_after:
        raise AwsSnsError(
            "aws_sns_expired_certificate",
            "Amazon SNS signing certificate is not valid.",
            403,
        )

    return certificate


def build_aws_sns_signing_string(envelope):
    """Build the canonical SNS string exactly as AWS signs it."""
    message_type = envelope.get("Type")

    if message_type == "Notification":
        field_names = [
            "Message",
            "MessageId",
        ]

        if envelope.get("Subject") is not None:
            field_names.append("Subject")

        field_names.extend([
            "Timestamp",
            "TopicArn",
            "Type",
        ])
    elif message_type in {
        "SubscriptionConfirmation",
        "UnsubscribeConfirmation",
    }:
        field_names = [
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ]
    else:
        raise AwsSnsError(
            "aws_sns_invalid_type",
            "Unsupported Amazon SNS message type.",
            400,
        )

    parts = []

    for field_name in field_names:
        value = envelope.get(field_name)

        if value is None:
            raise AwsSnsError(
                "aws_sns_missing_signature_field",
                (
                    "Amazon SNS message is missing the signed "
                    f"field {field_name}."
                ),
                400,
            )

        parts.append(field_name)
        parts.append(str(value))

    return "".join(
        f"{part}\n"
        for part in parts
    )


def validate_aws_sns_message(
    envelope,
    expected_topic_arn,
):
    """Verify TopicArn and the RSA signature of an SNS message."""
    message_type = envelope.get("Type")

    if message_type not in SNS_MESSAGE_TYPES:
        raise AwsSnsError(
            "aws_sns_invalid_type",
            "Unsupported Amazon SNS message type.",
            400,
        )

    topic_arn = str(
        envelope.get("TopicArn") or ""
    ).strip()

    if not expected_topic_arn:
        raise AwsSnsError(
            "aws_sns_topic_not_configured",
            "Amazon SNS Topic ARN is not configured for this route.",
            400,
        )

    if topic_arn != expected_topic_arn:
        raise AwsSnsError(
            "aws_sns_topic_mismatch",
            "Amazon SNS Topic ARN does not match this route.",
            403,
        )

    signature_version = str(
        envelope.get("SignatureVersion") or ""
    )

    if signature_version == "1":
        digest = hashes.SHA1()
    elif signature_version == "2":
        digest = hashes.SHA256()
    else:
        raise AwsSnsError(
            "aws_sns_signature_version_unsupported",
            "Amazon SNS signature version is not supported.",
            400,
        )

    certificate = _load_signing_certificate(
        envelope.get("SigningCertURL")
    )

    try:
        signature = base64.b64decode(
            envelope.get("Signature") or "",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise AwsSnsError(
            "aws_sns_invalid_signature",
            "Amazon SNS signature is invalid.",
            403,
        ) from exc

    signing_string = build_aws_sns_signing_string(
        envelope
    )

    try:
        certificate.public_key().verify(
            signature,
            signing_string.encode("utf-8"),
            padding.PKCS1v15(),
            digest,
        )
    except InvalidSignature as exc:
        raise AwsSnsError(
            "aws_sns_invalid_signature",
            "Amazon SNS signature verification failed.",
            403,
        ) from exc

    return True


def validate_confirmation_url(
    url,
    expected_topic_arn,
):
    """Validate SubscribeURL before confirming the subscription."""
    parsed = _validated_url_parts(url)

    if parsed.path not in {"", "/"}:
        raise AwsSnsError(
            "aws_sns_invalid_confirmation_url",
            "Amazon SNS confirmation URL path is invalid.",
            403,
        )

    if parsed.fragment:
        raise AwsSnsError(
            "aws_sns_invalid_confirmation_url",
            "Amazon SNS confirmation URL is invalid.",
            403,
        )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    if query.get("Action") != ["ConfirmSubscription"]:
        raise AwsSnsError(
            "aws_sns_invalid_confirmation_url",
            "Amazon SNS confirmation action is invalid.",
            403,
        )

    if query.get("TopicArn") != [expected_topic_arn]:
        raise AwsSnsError(
            "aws_sns_topic_mismatch",
            "Amazon SNS confirmation Topic ARN does not match.",
            403,
        )

    if not query.get("Token", [""])[0]:
        raise AwsSnsError(
            "aws_sns_invalid_confirmation_url",
            "Amazon SNS confirmation token is missing.",
            403,
        )

    return parsed


def confirm_aws_sns_subscription(
    subscribe_url,
    expected_topic_arn,
):
    """Confirm a validated SNS subscription."""
    validate_confirmation_url(
        subscribe_url,
        expected_topic_arn,
    )

    try:
        response = requests.get(
            subscribe_url,
            timeout=10,
            allow_redirects=False,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AwsSnsError(
            "aws_sns_confirmation_failed",
            "Amazon SNS subscription confirmation failed.",
            502,
        ) from exc

    return True
