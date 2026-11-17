"""Safe, structured diagnostics for every directory synchronization boundary."""

import logging
import re
import sqlite3
import traceback
import uuid
from functools import wraps

from peewee import IntegrityError

from app.modules.db.models import (
    AppLock, AuditLog, DirectorySyncBinding, DirectorySyncCurrent, DirectorySyncShift,
    DirectorySyncSource, Rotation, Team, TeamUser, User, UserGroup,
)
from app.modules.redaction import redact_secrets
from app.services.directory_sync.config import SyncBusy, SyncError


logger = logging.getLogger("oncall.directory_sync")
KNOWN_COLUMNS = frozenset(
    f"{model._meta.table_name}.{field.column_name}"
    for model in (AppLock, AuditLog, DirectorySyncBinding, DirectorySyncCurrent,
                  DirectorySyncShift, DirectorySyncSource, Rotation, Team, TeamUser, User, UserGroup)
    for field in model._meta.sorted_fields
)


def exception_chain(error):
    """Follow ORM wrappers and exception causes without cycling or inspecting locals."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = getattr(error, "orig", None) or error.__cause__ or error.__context__


def database_error_details(error):
    """Expose constraint categories and known columns, never SQL values or driver detail."""
    details = {}
    for cause in exception_chain(error):
        sqlstate = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
        if isinstance(sqlstate, str) and re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
            details["sqlstate"] = sqlstate
            kind = {"23502": "not_null", "23503": "foreign_key", "23505": "unique", "23514": "check"}.get(sqlstate)
            if kind:
                details["kind"] = kind
            diagnostic = getattr(cause, "diag", None)
            column = f"{getattr(diagnostic, 'table_name', '')}.{getattr(diagnostic, 'column_name', '')}"
            if column in KNOWN_COLUMNS:
                details["columns"] = [column]
        if cause.args and isinstance(cause.args[0], int):
            kind = {1048: "not_null", 1062: "unique", 1451: "foreign_key", 1452: "foreign_key", 3819: "check"}.get(cause.args[0])
            if kind:
                details.update(kind=kind, mysql_code=cause.args[0])
        if isinstance(cause, sqlite3.Error):
            code = getattr(cause, "sqlite_errorcode", None)
            if isinstance(code, int):
                details["sqlite_code"] = code
        if not isinstance(cause, (IntegrityError, sqlite3.IntegrityError)):
            continue
        details.setdefault("kind", "integrity")
        # SQLite's standard constraint messages contain column names, not values.
        # Even so, accept only identifiers that exist in our model definitions.
        message = str(cause)
        if message == "FOREIGN KEY constraint failed":
            details["kind"] = "foreign_key"
        elif message.startswith("CHECK constraint failed"):
            details["kind"] = "check"
        for prefix, kind in (("UNIQUE constraint failed: ", "unique"),
                             ("NOT NULL constraint failed: ", "not_null")):
            if message.startswith(prefix):
                details["kind"] = kind
                columns = message[len(prefix):].split(", ")
                if columns and all(column in KNOWN_COLUMNS for column in columns):
                    details["columns"] = columns
    return details


def error_message(error, prefix):
    """Return a safe message suitable for both source status and logs."""
    if isinstance(error, SyncError):
        return redact_secrets(str(error))
    detail = database_error_details(error)
    reason = {
        "foreign_key": "FOREIGN KEY constraint failed; a local reference is missing or still in use",
        "unique": "UNIQUE constraint failed; a local record already exists",
        "not_null": "NOT NULL constraint failed; a required database field is empty",
        "check": "CHECK constraint failed",
    }.get(detail.get("kind"))
    if reason:
        columns = ", ".join(detail.get("columns", []))
        return f"{prefix} ({type(error).__name__}: {reason}{'; ' + columns if columns else ''})"
    return f"{prefix} ({type(error).__name__})"


def log_failure(error, *, source_id=None, operation, http_status=None, rotation_id=None):
    """Record one failure once, including safe stack frames and all causal types."""
    if getattr(error, "_directory_sync_error_id", None):
        return error._directory_sync_error_id
    error_id = str(uuid.uuid4())
    exceptions = []
    for cause in exception_chain(error):
        exceptions.append({
            "type": type(cause).__name__,
            # Source lines and exception arguments may embed upstream secrets.
            "frames": [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                       for frame in traceback.extract_tb(cause.__traceback__)],
        })
    context = {
        "event_type": "directory_sync.error", "error_id": error_id,
        "source_id": source_id, "operation": operation, "http_status": http_status,
        "error_type": type(error).__name__, "error_message": error_message(error, "Synchronization failed"),
        "database_error": database_error_details(error), "exceptions": exceptions,
    }
    if rotation_id is not None:
        context["rotation_id"] = rotation_id
    level = logging.WARNING if isinstance(error, SyncBusy) else logging.ERROR
    logger.log(level, "Directory synchronization failed", extra={"extra": redact_secrets(context)})
    error._directory_sync_error_id = error_id
    return error_id


def logged_operation(operation):
    """Include failures while claiming, saving errors and releasing leases."""
    def decorate(function):
        @wraps(function)
        def wrapped(source_id, *args, **kwargs):
            try:
                return function(source_id, *args, **kwargs)
            except Exception as error:
                action = kwargs.get("mode", "run") if operation == "sync" else operation
                log_failure(error, source_id=source_id, operation=action)
                raise
        return wrapped
    return decorate
