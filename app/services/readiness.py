"""
Shared database readiness probe for /readyz and /metrics.

The probe never raises: failures are stored on the result and the
caller decides how to report them.
"""

from dataclasses import dataclass, field

from app.db import init_database
from app.modules.db.migrations import (
    get_applied_migrations,
    get_migration_files,
)


@dataclass
class ReadinessProbeResult:
    """Outcome of one probe pass; the errors are for logs only."""

    database_ok: bool = False
    database_error: Exception | None = None
    migration_error: Exception | None = None
    applied: int = 0
    total: int = 0
    pending: list[str] = field(default_factory=list)


def run_readiness_probe() -> ReadinessProbeResult:
    """
    Run SELECT 1 and the pending migration check.

    Opens a connection when none is open and closes it again if this
    call opened it, so readiness never depends on autoconnect behaviour.
    """

    result = ReadinessProbeResult()
    db = None
    db_was_closed = True

    try:
        try:
            db = init_database()
            db_was_closed = db.is_closed()

            if db_was_closed:
                db.connect(reuse_if_open=True)

            db.execute_sql("SELECT 1")
            result.database_ok = True
        except Exception as exc:
            result.database_error = exc
            return result

        try:
            applied = set(get_applied_migrations())
            on_disk = [
                filename.replace(".py", "")
                for filename in get_migration_files()
            ]
            result.applied = len(applied)
            result.total = len(on_disk)
            result.pending = [name for name in on_disk if name not in applied]
        except Exception as exc:
            result.migration_error = exc

        return result
    finally:
        if db is not None and db_was_closed and not db.is_closed():
            try:
                db.close()
            except Exception:
                pass
