from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db.models import LoginThrottle
from app.services.auth_throttle import (
    clear_login_account_failures,
    login_retry_after,
    record_login_failure,
)
from app.settings import Config


def _tight_limits(monkeypatch):
    monkeypatch.setattr(Config, "AUTH_LOGIN_IP_MAX_FAILURES", 2)
    monkeypatch.setattr(Config, "AUTH_LOGIN_IP_WINDOW_SECONDS", 60)
    monkeypatch.setattr(Config, "AUTH_LOGIN_IP_BLOCK_SECONDS", 120)
    monkeypatch.setattr(Config, "AUTH_LOGIN_ACCOUNT_MAX_FAILURES", 2)
    monkeypatch.setattr(Config, "AUTH_LOGIN_ACCOUNT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(Config, "AUTH_LOGIN_ACCOUNT_BLOCK_SECONDS", 120)


def test_login_throttle_blocks_after_configured_failures(db, monkeypatch):
    _tight_limits(monkeypatch)
    now = utc_now()

    record_login_failure("admin", "203.0.113.9", now=now)
    assert login_retry_after("admin", "203.0.113.9", now=now) == 0

    record_login_failure("admin", "203.0.113.9", now=now + timedelta(seconds=1))
    retry_after = login_retry_after(
        "admin",
        "203.0.113.9",
        now=now + timedelta(seconds=1),
    )
    assert retry_after >= 120


def test_login_throttle_does_not_store_raw_ip_or_username(db, monkeypatch):
    _tight_limits(monkeypatch)
    record_login_failure("SensitiveAdmin", "203.0.113.77")

    rows = list(LoginThrottle.select())
    assert len(rows) == 2
    serialized = " ".join(f"{row.scope}:{row.key_hash}" for row in rows)
    assert "SensitiveAdmin" not in serialized
    assert "203.0.113.77" not in serialized
    assert all(len(row.key_hash) == 64 for row in rows)


def test_success_clears_account_counter_but_not_ip_counter(db, monkeypatch):
    _tight_limits(monkeypatch)
    record_login_failure("admin", "203.0.113.9")

    clear_login_account_failures("admin")

    rows = list(LoginThrottle.select())
    assert [row.scope for row in rows] == ["ip"]
