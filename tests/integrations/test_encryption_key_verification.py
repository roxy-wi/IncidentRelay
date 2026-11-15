"""Startup and upgrade protection, exercised on SQLite and PostgreSQL in CI."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from types import SimpleNamespace

import pytest
from peewee import IntegrityError, OperationalError

from app import create_app
from app.check_encryption_key import main as check_key
from app.modules.crypto import encrypt_secret
from app.modules.db.models import (
    AutomationExecution,
    EncryptionKeyVerification,
    EventOrchestration,
    EventOrchestrationVersion,
    OrchestrationExecution,
    OrchestrationWebhookAction,
    SsoProvider,
)
from app.services import encryption_keys as keys
from app.settings import Config, Settings
from tests.factories import create_group, unique


migration = import_module("app.migrations.20261109010000_encryption_key_verification")
KEY_A = "original-encryption-key-for-tests"
KEY_B = "changed-encryption-key-for-tests"


def config(key=KEY_A, *, sso_key=None):
    return SimpleNamespace(
        SECRET_KEY=key,
        SECRET_ENCRYPTION_KEY=key,
        SSO_SECRET_ENCRYPTION_KEY=sso_key or key,
    )


@pytest.fixture(autouse=True)
def uninitialized_verifier(db, monkeypatch):
    EncryptionKeyVerification.update(key_check=None, initialized_at=None).execute()
    monkeypatch.setattr(
        keys, "settings", Settings(path="absent-test-config", environ={})
    )
    yield
    EncryptionKeyVerification.update(key_check=None, initialized_at=None).execute()


def stored_ciphertext(field, value):
    """Populate real tables without exercising an unrelated API authorization path."""
    if field.model is SsoProvider:
        return SsoProvider.create(
            slug=unique("sso"),
            label="SSO",
            enabled=False,
            deleted=True,
            **{field.name: value},
        )
    group = create_group()
    action = OrchestrationWebhookAction.create(
        group=group,
        name=unique("action"),
        url="https://example.com/hook",
        enabled=False,
        deleted=True,
        headers_encrypted=value if field.model is OrchestrationWebhookAction else None,
    )
    if field.model is OrchestrationWebhookAction:
        return action
    orchestration = EventOrchestration.create(group=group, name=unique("orchestration"))
    version = EventOrchestrationVersion.create(
        orchestration=orchestration, version_number=1
    )
    execution = OrchestrationExecution.create(
        group=group, orchestration=orchestration, version=version
    )
    return AutomationExecution.create(
        action=action,
        group=group,
        orchestration_execution=execution,
        idempotency_key=unique("execution"),
        status="succeeded",
        **{field.name: value},
    )


def test_verifier_survives_restarts_and_rejects_new_key(db):
    keys.verify_encryption_key(config())
    first = EncryptionKeyVerification.get_by_id(1)
    assert first.initialized_at is not None
    assert KEY_A not in first.key_check
    assert keys.key_matches(KEY_A, first.key_check)
    assert keys.make_key_check(KEY_A) != first.key_check
    db.close()
    keys.verify_encryption_key(config())
    assert db.is_closed()
    db.connect()
    assert EncryptionKeyVerification.get_by_id(1).key_check == first.key_check
    with pytest.raises(
        keys.EncryptionKeyVerificationError, match="Restore the original"
    ):
        keys.verify_encryption_key(config(KEY_B))
    assert EncryptionKeyVerification.get_by_id(1).key_check == first.key_check


@pytest.mark.parametrize(
    "field",
    [
        OrchestrationWebhookAction.headers_encrypted,
        AutomationExecution.request_headers_encrypted,
        AutomationExecution.request_body_encrypted,
        SsoProvider.client_secret_encrypted,
        SsoProvider.saml_sp_private_key_encrypted,
    ],
)
@pytest.mark.parametrize("wrong", [False, True])
def test_upgrade_checks_all_existing_ciphertexts(db, field, wrong):
    # A valid first record must not hide a later ciphertext with another key.
    stored_ciphertext(field, encrypt_secret("first-secret", key=KEY_A))
    value = encrypt_secret("second-secret", key=KEY_B if wrong else KEY_A)
    stored_ciphertext(field, value)
    if wrong:
        with pytest.raises(keys.EncryptionKeyVerificationError) as caught:
            keys.verify_encryption_key(config())
        assert field.column_name in str(caught.value)
        for secret in (KEY_A, KEY_B, "second-secret", value):
            assert secret not in str(caught.value)
        assert EncryptionKeyVerification.get_by_id(1).key_check is None
    else:
        keys.verify_encryption_key(config())
        assert keys.key_matches(KEY_A, EncryptionKeyVerification.get_by_id(1).key_check)


def test_separate_sso_key_is_respected_during_upgrade(db):
    stored_ciphertext(
        SsoProvider.client_secret_encrypted, encrypt_secret("sso", key=KEY_B)
    )
    stored_ciphertext(
        OrchestrationWebhookAction.headers_encrypted, encrypt_secret("main", key=KEY_A)
    )
    keys.verify_encryption_key(config(sso_key=KEY_B))
    assert keys.key_matches(KEY_A, EncryptionKeyVerification.get_by_id(1).key_check)


@pytest.mark.parametrize("value", ["corrupt ciphertext", "gAAAA-invalid"])
def test_corrupt_legacy_ciphertext_does_not_initialize_verifier(db, value):
    stored_ciphertext(OrchestrationWebhookAction.headers_encrypted, value)
    with pytest.raises(
        keys.EncryptionKeyVerificationError, match="cannot be decrypted"
    ):
        keys.verify_encryption_key(config())
    assert EncryptionKeyVerification.get_by_id(1).key_check is None


@pytest.mark.parametrize("matching", [True, False])
def test_runtime_config_verifier_remains_compatible(db, monkeypatch, matching):
    legacy = keys.make_key_check(KEY_A if matching else KEY_B)
    parser = keys.settings.parser
    parser.add_section("entrypoint")
    parser.set("entrypoint", "secret_encryption_key_check", legacy)
    if matching:
        keys.verify_encryption_key(config())
        assert keys.key_matches(KEY_A, EncryptionKeyVerification.get_by_id(1).key_check)
    else:
        with pytest.raises(
            keys.EncryptionKeyVerificationError, match="Runtime.*mismatch"
        ):
            keys.verify_encryption_key(config())
        assert EncryptionKeyVerification.get_by_id(1).key_check is None


@pytest.mark.parametrize("check", ["", "invalid", "pbkdf2_sha256:9999999999:aa:bb"])
def test_corrupt_database_verifier_is_not_overwritten(db, check):
    EncryptionKeyVerification.update(key_check=check).execute()
    with pytest.raises(
        keys.EncryptionKeyVerificationError, match="verifier is invalid"
    ):
        keys.verify_encryption_key(config())
    assert EncryptionKeyVerification.get_by_id(1).key_check == check


@pytest.mark.parametrize("role", [None, "scheduler", "telegram", "slack"])
def test_every_application_role_stops_with_changed_key(db, monkeypatch, role):
    keys.verify_encryption_key()
    monkeypatch.setattr(Config, "SECRET_ENCRYPTION_KEY", KEY_B)
    with pytest.raises(keys.EncryptionKeyVerificationError, match="Database.*mismatch"):
        create_app(log_role=role)


def test_database_failure_and_missing_schema_fail_closed(db, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError("sensitive database credentials")

    with monkeypatch.context() as patch:
        patch.setattr(db, "execute_sql", unavailable)
        with pytest.raises(
            keys.EncryptionKeyVerificationError, match="connectivity"
        ) as caught:
            keys.verify_encryption_key(config())
        assert "sensitive" not in str(caught.value)
    with db.atomic() as transaction:
        migration.downgrade()
        with pytest.raises(
            keys.EncryptionKeyVerificationError, match="manage.py migrate"
        ):
            keys.verify_encryption_key(config())
        transaction.rollback()


def test_migration_preserves_initialized_key_and_enforces_singleton(db):
    keys.verify_encryption_key(config())
    before = EncryptionKeyVerification.get_by_id(1).key_check
    migration.upgrade()
    assert EncryptionKeyVerification.select().count() == 1
    assert EncryptionKeyVerification.get_by_id(1).key_check == before
    with pytest.raises(IntegrityError), db.atomic():
        EncryptionKeyVerification.create(id=2)


def test_missing_verification_record_cannot_be_recreated_at_startup(db):
    with db.atomic() as transaction:
        EncryptionKeyVerification.delete().execute()
        with pytest.raises(
            keys.EncryptionKeyVerificationError, match="record is missing"
        ):
            keys.verify_encryption_key(config())
        assert EncryptionKeyVerification.select().count() == 0
        transaction.rollback()


def test_empty_explicit_key_inherits_main_key_and_empty_effective_key_fails(db):
    effective = config()
    effective.SECRET_ENCRYPTION_KEY = ""
    keys.verify_encryption_key(effective)
    assert keys.key_matches(KEY_A, EncryptionKeyVerification.get_by_id(1).key_check)
    effective.SECRET_KEY = ""
    with pytest.raises(
        keys.EncryptionKeyVerificationError, match="effective encryption key"
    ):
        keys.verify_encryption_key(effective)


def test_failed_verifier_commit_leaves_bootstrap_uninitialized(db, monkeypatch):
    def fail(*args, **kwargs):
        raise OperationalError("sensitive database credentials")

    with monkeypatch.context() as patch:
        patch.setattr(EncryptionKeyVerification, "save", fail)
        with pytest.raises(keys.EncryptionKeyVerificationError, match="connectivity"):
            keys.verify_encryption_key(config())
    assert EncryptionKeyVerification.get_by_id(1).key_check is None
    assert EncryptionKeyVerification.get_by_id(1).initialized_at is None
    keys.verify_encryption_key(config())


@pytest.mark.parametrize("second_key", [KEY_A, KEY_B])
def test_concurrent_initialization_cannot_accept_conflicting_keys(db, second_key):
    barrier = Barrier(2)

    def start(key):
        with db.connection_context():
            barrier.wait(timeout=10)
            try:
                keys.verify_encryption_key(config(key))
            except keys.EncryptionKeyVerificationError:
                return key, False
            return key, True

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start, key) for key in (KEY_A, second_key)]
        results = [future.result(timeout=15) for future in futures]
    assert sum(success for _, success in results) == (2 if second_key == KEY_A else 1)
    check = EncryptionKeyVerification.get_by_id(1).key_check
    assert all(keys.key_matches(key, check) == success for key, success in results)


def test_cli_reports_mismatch_without_secrets(db, monkeypatch, capsys):
    assert check_key() == 0
    monkeypatch.setattr(Config, "SECRET_ENCRYPTION_KEY", KEY_B)
    assert check_key() == 1
    output = capsys.readouterr()
    assert "Restore the original" in output.err
    assert KEY_B not in output.err


@pytest.mark.parametrize("option", ["SECRET_KEY", "SECRET_ENCRYPTION_KEY"])
@pytest.mark.parametrize("from_file", [False, True])
def test_new_pod_config_uses_effective_environment_key(db, tmp_path, option, from_file):
    """Two processes with disposable config files share only the database verifier."""
    root = Path(__file__).resolve().parents[2]
    source = Path(
        os.environ.get("INCIDENTRELAY_CONFIG_FILE")
        or os.environ["INCEDENTRELAY_CONFIG_FILE"]
    )
    # This shim only permits importing the existing POSIX metrics module on Windows.
    script = """
import sys, types
if sys.platform == 'win32':
    module = types.ModuleType('fcntl')
    def unsupported(*args):
        raise RuntimeError('POSIX file locking is unavailable on Windows')
    module.flock = unsupported
    module.LOCK_EX = 2
    module.LOCK_SH = 1
    sys.modules['fcntl'] = module
from app.check_encryption_key import main
raise SystemExit(main())
"""

    def pod(key, number):
        path = tmp_path / f"pod-{number}.conf"
        path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("INCIDENTRELAY__")
        }
        env["INCIDENTRELAY_CONFIG_FILE"] = str(path)
        env["INCIDENTRELAY__MAIN__SECRET_ENCRYPTION_KEY"] = ""
        name = f"INCIDENTRELAY__MAIN__{option}"
        if from_file:
            env.pop(name, None)
            secret = tmp_path / f"secret-{number}"
            secret.write_text(key + "\n", encoding="utf-8")
            env[name + "__FILE"] = str(secret)
        else:
            env[name] = key
        return subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            cwd=root,
            capture_output=True,
            text=True,
        )

    assert pod(KEY_A, 1).returncode == 0
    assert pod(KEY_A, 2).returncode == 0
    changed = pod(KEY_B, 3)
    assert changed.returncode == 1
    assert "Database encryption key verifier mismatch" in changed.stderr
    assert KEY_A not in changed.stderr and KEY_B not in changed.stderr
