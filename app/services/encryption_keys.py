"""Verify the configured encryption key against durable installation state."""

import hashlib
import hmac
import re
import secrets

from cryptography.fernet import InvalidToken
from peewee import DatabaseError

from app.db import init_database
from app.modules.common import utc_now
from app.modules.crypto import decrypt_secret
from app.modules.db.models import (
    AutomationExecution,
    EncryptionKeyVerification,
    DirectorySyncSource,
    OrchestrationWebhookAction,
    SsoProvider,
)
from app.modules.db.transactions import lock_row, write_transaction
from app.settings import Config, settings


# Keep the runtime-file verifier format introduced by the Docker entrypoint.
KEY_CHECK_ITERATIONS = 200_000
KEY_CHECK_PATTERN = re.compile(r"pbkdf2_sha256:200000:([0-9a-f]{32}):([0-9a-f]{64})")
RESTORE_KEY = (
    "Restore the original main.secret_encryption_key (or main.secret_key when "
    "the encryption key is empty), including environment and __FILE overrides. "
    "Do not delete or reset the database verifier; key rotation is not supported."
)


class EncryptionKeyVerificationError(RuntimeError):
    """Startup must stop before accessing or writing encrypted secrets."""


def make_key_check(key):
    """Return a salted verifier compatible with the existing runtime config."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", key.encode("utf-8"), salt, KEY_CHECK_ITERATIONS
    )
    return f"pbkdf2_sha256:{KEY_CHECK_ITERATIONS}:{salt.hex()}:{digest.hex()}"


def key_matches(key, check):
    """Validate the stored format before evaluating its bounded work factor."""
    match = KEY_CHECK_PATTERN.fullmatch(check)
    if match is None:
        raise EncryptionKeyVerificationError(
            "Encryption key verifier is invalid. Restore intact verification state "
            "from backup; do not replace it with the current key."
        )
    salt, digest = match.groups()
    actual = hashlib.pbkdf2_hmac(
        "sha256", key.encode("utf-8"), bytes.fromhex(salt), KEY_CHECK_ITERATIONS
    )
    return hmac.compare_digest(actual, bytes.fromhex(digest))


def _verify_existing_secrets(key, sso_key):
    """Authenticate every ciphertext, including disabled and historical rows.

    SSO may use its own key. Check those records using its effective setting,
    so a valid independent SSO key is not mistaken for a wrong main key.
    No ciphertext or decrypted value is included in failures.
    """
    fields = (
        (DirectorySyncSource.headers_encrypted, key),
        (DirectorySyncSource.preview_encrypted, key),
        (OrchestrationWebhookAction.headers_encrypted, key),
        (AutomationExecution.request_headers_encrypted, key),
        (AutomationExecution.request_body_encrypted, key),
        (SsoProvider.client_secret_encrypted, sso_key),
        (SsoProvider.saml_sp_private_key_encrypted, sso_key),
    )
    for field, effective_key in fields:
        rows = (
            field.model.select(field)
            .where(field.is_null(False), field != "")
            .tuples()
            .iterator()
        )
        for (value,) in rows:
            try:
                decrypt_secret(value, key=effective_key)
            except (InvalidToken, ValueError, UnicodeError):
                raise EncryptionKeyVerificationError(
                    "Cannot initialize encryption key verification: an existing "
                    f"{field.model._meta.table_name}.{field.column_name} value cannot "
                    "be decrypted. Check the original SSO key if configured separately. "
                    + RESTORE_KEY
                ) from None


def verify_encryption_key(config=Config):
    """Verify at every process startup, initializing only after safe bootstrap.

    The migration creates an empty singleton. Locking it serializes competing
    first starts on PostgreSQL; SQLite reserves writes before reading. The
    verifier is committed only after all legacy ciphertexts authenticate.
    Existing processes must be stopped during the first upgrade/bootstrap.
    """
    key = config.SECRET_ENCRYPTION_KEY or config.SECRET_KEY
    if not key:
        raise EncryptionKeyVerificationError(
            "An effective encryption key is required. " + RESTORE_KEY
        )
    legacy_check = settings.parser.get(
        "entrypoint", "secret_encryption_key_check", fallback=""
    )
    if legacy_check and not key_matches(key, legacy_check):
        raise EncryptionKeyVerificationError(
            "Runtime encryption key verifier mismatch. " + RESTORE_KEY
        )

    database = init_database()
    opened = database.is_closed()
    try:
        if opened:
            database.connect(reuse_if_open=True)
        with write_transaction():
            record = lock_row(
                EncryptionKeyVerification.select().where(
                    EncryptionKeyVerification.id == 1
                )
            )
            if record is None:
                raise EncryptionKeyVerificationError(
                    "Encryption key verification record is missing. Run python manage.py migrate "
                    "before starting IncidentRelay; restore verification state if it was deleted."
                )
            if record.key_check is not None:
                if not key_matches(key, record.key_check):
                    raise EncryptionKeyVerificationError(
                        "Database encryption key verifier mismatch. " + RESTORE_KEY
                    )
                return
            _verify_existing_secrets(key, config.SSO_SECRET_ENCRYPTION_KEY or key)
            record.key_check = make_key_check(key)
            record.initialized_at = utc_now()
            record.save(
                only=[
                    EncryptionKeyVerification.key_check,
                    EncryptionKeyVerification.initialized_at,
                ]
            )
    except DatabaseError:
        raise EncryptionKeyVerificationError(
            "Cannot verify the encryption key against the database. Check database connectivity "
            "and run python manage.py migrate before starting IncidentRelay."
        ) from None
    finally:
        if opened and not database.is_closed():
            database.close()
