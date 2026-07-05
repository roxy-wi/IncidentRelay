import re

from flask import jsonify
from peewee import DoesNotExist, IntegrityError


def _extract_sqlite_unique_fields(message: str) -> list[str]:
    """
    Parse SQLite messages like:
    UNIQUE constraint failed: alert_route.team_id, alert_route.name
    """
    match = re.search(r"UNIQUE constraint failed:\s*(.+)", message, re.IGNORECASE)
    if not match:
        return []

    fields = []
    for item in match.group(1).split(","):
        column = item.strip().split(".")[-1]
        if column:
            fields.append(column)

    return fields


def _extract_postgres_constraint(message: str) -> str | None:
    """
    Parse PostgreSQL messages like:
    duplicate key value violates unique constraint "alert_route_team_id_name"
    """
    match = re.search(
        r'violates unique constraint\s+"([^"]+)"',
        message,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _make_duplicate_message(fields: list[str], constraint: str | None) -> str:
    joined = " ".join(fields or [])
    constraint_name = constraint or ""

    if "alert_route" in constraint_name or {"team_id", "name"}.issubset(set(fields)):
        return "Route with this name already exists in this team"

    if "notificationchannel" in constraint_name or {"team_id", "name"}.issubset(set(fields)):
        return "Resource with this name already exists in this team"

    if "slug" in fields or "slug" in constraint_name:
        return "Resource with this slug already exists"

    if "username" in fields or "username" in constraint_name:
        return "User with this username already exists"

    if "email" in fields or "email" in constraint_name:
        return "User with this email already exists"

    return "Resource already exists"


def handle_integrity_error(exc: IntegrityError):
    """
    Convert database constraint errors to API errors.

    Covers:
    - unique constraints;
    - foreign key constraints;
    - not-null/check constraints.

    This prevents API endpoints from returning 500 for expected validation
    problems discovered by the database.
    """
    raw_message = str(exc)
    message_lower = raw_message.lower()

    if "unique constraint" in message_lower or "duplicate key" in message_lower:
        fields = _extract_sqlite_unique_fields(raw_message)
        constraint = _extract_postgres_constraint(raw_message)

        return jsonify({
            "error": "conflict",
            "message": _make_duplicate_message(fields, constraint),
            "details": [
                {
                    "type": "unique_constraint",
                }
            ],
        }), 409

    if "foreign key" in message_lower:
        return jsonify({
            "error": "constraint_violation",
            "message": "Related resource was not found or cannot be used",
            "details": [
                {
                    "type": "foreign_key_constraint",
                }
            ],
        }), 400

    if "not null" in message_lower or "check constraint" in message_lower:
        return jsonify({
            "error": "constraint_violation",
            "message": "Database constraint violation",
            "details": [
                {
                    "type": "constraint_violation",
                }
            ],
        }), 400

    return jsonify({
        "error": "constraint_violation",
        "message": "Database constraint violation",
        "details": [
            {
                "type": "integrity_error",
            }
        ],
    }), 400


def handle_not_found_error(exc: DoesNotExist):
    """Convert Peewee DoesNotExist to a normal API 404."""
    return jsonify({
        "error": "not_found",
        "message": "Resource was not found",
    }), 404
