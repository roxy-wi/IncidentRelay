"""Retry policy shared by technical recovery and operational Incident delivery."""

from datetime import timedelta


def delivery_attempt(
    send,
    *,
    attempt,
    now,
    max_attempts=5,
    base_seconds=30,
    max_seconds=3600,
    error_text=str,
):
    """Return persisted outcome fields for one bounded delivery attempt.

    The caller owns claiming, transactions and lifecycle checks. Transport
    success and a database commit cannot be atomic; delivery is at-least-once.
    """
    values = {"attempts": attempt, "updated_at": now}
    try:
        status, sent = send()
    except Exception as exc:
        values["last_error"] = error_text(exc)[:2000]
        values["status"] = "failed" if attempt >= max_attempts else "pending"
        if values["status"] == "pending":
            seconds = min(base_seconds * (2 ** (attempt - 1)), max_seconds)
            values["next_attempt_at"] = now + timedelta(seconds=seconds)
    else:
        values.update(
            status=status,
            delivered_count=max(int(sent or 0), 0),
            delivered_at=now if status == "sent" else None,
            last_error=None,
        )
    return values
