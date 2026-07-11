import re
from collections.abc import Mapping
from typing import Any


REDACTED = "***REDACTED***"


SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
)


REDACTION_PATTERNS = (
    # Telegram Bot API:
    # https://api.telegram.org/bot123456:ABC/sendMessage
    (
        re.compile(
            r"(/bot)(\d{5,20}:[A-Za-z0-9_-]{20,})",
            re.IGNORECASE,
        ),
        rf"\1{REDACTED}",
    ),

    # Query params:
    # ?token=abc
    # &api_token=abc
    # &password=abc
    (
        re.compile(
            r"([?&](?:token|api_token|access_token|refresh_token|bot_token|telegram_token|password|secret|api_key|key)=)([^&\s]+)",
            re.IGNORECASE,
        ),
        rf"\1{REDACTED}",
    ),

    # Headers rendered as text:
    # Authorization: Bearer xxx
    # Proxy-Authorization: Basic xxx
    (
        re.compile(
            r"((?:Authorization|Proxy-Authorization)\s*:\s*)(?:Bearer|Basic)?\s*[^\s,;]+",
            re.IGNORECASE,
        ),
        rf"\1{REDACTED}",
    ),

    # URL credentials:
    # http://user:password@example.com
    (
        re.compile(r"://([^:/?#\s]+):([^@/\s]+)@"),
        rf"://\1:{REDACTED}@",
    ),
    (
        re.compile(
            r"""
            (
                \b
                (?:
                    password
                    |passwd
                    |secret
                    |client_secret
                    |token
                    |api_token
                    |access_token
                    |refresh_token
                    |bot_token
                    |telegram_token
                    |api_key
                    |private_key
                )
                \s*[=:]\s*
            )
            (
                "(?:\\.|[^"])*"
                |
                '(?:\\.|[^'])*'
                |
                [^\s,;&]+
            )
            """,
            re.IGNORECASE | re.VERBOSE,
        ),
        rf"\1{REDACTED}",
    ),
)


def is_sensitive_key(key: Any) -> bool:
    """Return True if a dictionary key looks like it may contain a secret."""

    key_text = str(key).lower()

    return any(part in key_text for part in SENSITIVE_KEY_PARTS)


def redact_string(value: str) -> str:
    """Redact secrets from a string."""

    result = value

    for pattern, replacement in REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


def redact_secrets(value: Any) -> Any:
    """Recursively redact secrets from common Python objects."""

    if value is None:
        return None

    if isinstance(value, BaseException):
        return redact_string(str(value))

    if isinstance(value, str):
        return redact_string(value)

    if isinstance(value, bytes):
        return redact_string(value.decode("utf-8", errors="replace"))

    if isinstance(value, Mapping):
        redacted = {}

        for key, item in value.items():
            if is_sensitive_key(key):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_secrets(item)

        return redacted

    if isinstance(value, list):
        return [redact_secrets(item) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)

    if isinstance(value, set):
        return {redact_secrets(item) for item in value}

    return value
