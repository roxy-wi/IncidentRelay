"""Project-wide encryption helpers for secrets stored in the database."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet

from app.settings import Config


def _fernet(raw_key: str | None = None) -> Fernet:
    """Build a stable Fernet key from an explicit or application secret."""
    raw_key = (
        raw_key
        or getattr(Config, "SECRET_ENCRYPTION_KEY", None)
        or Config.SECRET_KEY
    )
    digest = hashlib.sha256(str(raw_key).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None, *, key: str | None = None) -> str | None:
    """Encrypt a UTF-8 string for database storage."""
    if value in (None, ""):
        return None
    return _fernet(key).encrypt(str(value).encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None, *, key: str | None = None) -> str | None:
    """Decrypt a UTF-8 string previously produced by :func:`encrypt_secret`."""
    if not value:
        return None
    return _fernet(key).decrypt(value.encode("utf-8")).decode("utf-8")


def encrypt_json(value: Any) -> str | None:
    """Serialize and encrypt a JSON-compatible value."""
    if value is None:
        return None
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return encrypt_secret(encoded)


def decrypt_json(value: str | None, *, default: Any = None) -> Any:
    """Decrypt and deserialize a JSON-compatible value."""
    plaintext = decrypt_secret(value)
    if plaintext is None:
        return default
    return json.loads(plaintext)


__all__ = [
    "decrypt_json",
    "decrypt_secret",
    "encrypt_json",
    "encrypt_secret",
]
