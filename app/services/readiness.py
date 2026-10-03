"""
Shared database readiness probe.

/readyz (app/views/health_view.py) and /metrics (app/views/metrics_view.py)
run the same two checks: the database must answer SELECT 1, and the number
of applied migrations must match the migration files on disk. This module
owns that logic so the two endpoints cannot drift apart.

The probe never raises. Failures are stored on the result and the caller
decides how to report them: /readyz answers 503, /metrics degrades its
gauges. Both log with their own logger and keep the original exception
through ``exc_info``.
"""

from dataclasses import dataclass, field

from app.db import init_database
from app.modules.db.migrations import (
    get_applied_migrations,
    get_migration_files,
)


@dataclass
class ReadinessProbeResult:
    """
    Outcome of one probe pass.

    ``database_error`` and ``migration_error`` carry the caught exceptions
    for logging; both are None when the check passed. Exceptions can hold
    connection strings with credentials, so they are for logs only and
    must never end up in a response body (see tests/release).
    """

    database_ok: bool = False
    database_error: Exception | None = None
    migration_error: Exception | None = None
    applied: int = 0
    total: int = 0
    pending: list[str] = field(default_factory=list)


def run_readiness_probe() -> ReadinessProbeResult:
    """
    Run SELECT 1 and the pending migration check.

    Opens a database connection when none is open, keeps it open for
    both checks and closes it again if this call opened it. Closing it
    in between and relying on an implicit reconnect in
    get_applied_migrations() would make readiness depend on
    Peewee/backend autoconnect behaviour. Migration names on disk are
    normalized the same way migrations.migrate() compares them: files
    carry the .py suffix, the migration table does not.
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
