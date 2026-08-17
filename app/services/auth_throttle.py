"""Database-backed rate limiting for password login attempts."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from peewee import IntegrityError

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db.models import LoginThrottle
from app.settings import Config


_SCOPE_IP = "ip"
_SCOPE_ACCOUNT = "account"


def _normalize(scope: str, value) -> str:
    text = str(value or "").strip().lower()
    return text or "unknown"


def _key_hash(scope: str, value) -> str:
    normalized = _normalize(scope, value)
    return hashlib.sha256(f"{scope}:{normalized}".encode("utf-8")).hexdigest()


def _policy(scope: str):
    if scope == _SCOPE_IP:
        return (
            int(getattr(Config, "AUTH_LOGIN_IP_MAX_FAILURES", 10)),
            int(getattr(Config, "AUTH_LOGIN_IP_WINDOW_SECONDS", 60)),
            int(getattr(Config, "AUTH_LOGIN_IP_BLOCK_SECONDS", 300)),
        )
    return (
        int(getattr(Config, "AUTH_LOGIN_ACCOUNT_MAX_FAILURES", 20)),
        int(getattr(Config, "AUTH_LOGIN_ACCOUNT_WINDOW_SECONDS", 300)),
        int(getattr(Config, "AUTH_LOGIN_ACCOUNT_BLOCK_SECONDS", 300)),
    )


def _keys(username, remote_addr):
    return (
        (_SCOPE_IP, remote_addr),
        (_SCOPE_ACCOUNT, username),
    )


def login_retry_after(username, remote_addr, *, now=None) -> int:
    """Return seconds until login may be retried, or zero when allowed."""
    now = now or utc_now()
    retry_after = 0
    for scope, value in _keys(username, remote_addr):
        row = LoginThrottle.get_or_none(
            LoginThrottle.key_hash == _key_hash(scope, value)
        )
        if not row or not row.blocked_until or row.blocked_until <= now:
            continue
        retry_after = max(
            retry_after,
            int((row.blocked_until - now).total_seconds()) + 1,
        )
    return max(retry_after, 0)


def _record_failure(scope, value, *, now):
    max_failures, window_seconds, block_seconds = _policy(scope)
    if max_failures <= 0:
        return

    key_hash = _key_hash(scope, value)
    defaults = {
        "scope": scope,
        "failure_count": 1,
        "window_started_at": now,
        "blocked_until": (
            now + timedelta(seconds=max(block_seconds, 1))
            if max_failures <= 1
            else None
        ),
        "updated_at": now,
    }

    try:
        row, created = LoginThrottle.get_or_create(
            key_hash=key_hash,
            defaults=defaults,
        )
    except IntegrityError:
        # Another worker created the same hashed bucket concurrently.
        row = LoginThrottle.get(LoginThrottle.key_hash == key_hash)
        created = False

    if created:
        return

    with db.atomic():
        row = LoginThrottle.get_by_id(row.id)
        if (
            not row.window_started_at
            or row.window_started_at <= now - timedelta(seconds=window_seconds)
        ):
            row.failure_count = 1
            row.window_started_at = now
            row.blocked_until = None
        else:
            row.failure_count = int(row.failure_count or 0) + 1

        if row.failure_count >= max_failures:
            row.blocked_until = now + timedelta(seconds=max(block_seconds, 1))

        row.updated_at = now
        row.save()


def record_login_failure(username, remote_addr, *, now=None) -> None:
    """Increment both per-IP and per-account counters."""
    now = now or utc_now()
    for scope, value in _keys(username, remote_addr):
        _record_failure(scope, value, now=now)

    # Keep the table bounded without a dedicated scheduler job.
    LoginThrottle.delete().where(
        LoginThrottle.updated_at < now - timedelta(days=7)
    ).execute()


def clear_login_account_failures(username) -> None:
    """Clear the account counter after a successful authentication."""
    LoginThrottle.delete().where(
        LoginThrottle.key_hash == _key_hash(_SCOPE_ACCOUNT, username)
    ).execute()


__all__ = [
    "clear_login_account_failures",
    "login_retry_after",
    "record_login_failure",
]
