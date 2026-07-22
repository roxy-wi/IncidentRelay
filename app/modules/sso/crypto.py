"""SSO secret encryption using the historically configured SSO key."""

from app.modules.crypto import decrypt_secret as _decrypt_secret
from app.modules.crypto import encrypt_secret as _encrypt_secret
from app.settings import Config


def encrypt_secret(value: str | None) -> str | None:
    return _encrypt_secret(
        value,
        key=Config.SSO_SECRET_ENCRYPTION_KEY or Config.SECRET_KEY,
    )


def decrypt_secret(value: str | None) -> str | None:
    return _decrypt_secret(
        value,
        key=Config.SSO_SECRET_ENCRYPTION_KEY or Config.SECRET_KEY,
    )


__all__ = ["decrypt_secret", "encrypt_secret"]
