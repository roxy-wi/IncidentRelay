"""Short alert log for the direct message to the on-call user.

Built from the alert group itself (created, assigned, reminders, shelves,
acknowledged, resolved), not from the raw event table. The raw table also
holds delivery and routing details that are not useful in a page.
"""

from html import escape

from app.modules.common import utc_now
from app.modules.db.models import AlertGroupShelve
from app.notifiers.telegram import timefmt


MAX_LINES = 12


def journal_lines(alert, event_type="refresh", now=None):
    """Return the log lines, oldest first, as ``<offset>  <text>`` strings."""

    now = now or utc_now()
    start = getattr(alert, "first_seen_at", None) or now
    entries = [(start, "alert created")]

    assigned = _assigned_text(alert)

    if assigned:
        entries.append((start, assigned))

    for shelf in _shelves(alert):
        entries.append((shelf.shelved_at, _shelved_text(shelf)))

        if shelf.unshelved_at:
            entries.append(
                (
                    shelf.unshelved_at,
                    f"unshelved: {_person(getattr(shelf, 'unshelved_by', None))}",
                )
            )

    reminders = int(getattr(alert, "reminder_count", 0) or 0)

    if event_type == "reminder":
        # The counter grows after the reminder is sent.
        reminders += 1

    if reminders:
        reminded_at = now if event_type == "reminder" else (
            getattr(alert, "last_notification_at", None) or now
        )
        entries.append((reminded_at, f"reminders: {reminders}"))

    acknowledged_at = getattr(alert, "acknowledged_at", None)

    if acknowledged_at:
        who = _person(getattr(alert, "acknowledged_by", None))
        entries.append((acknowledged_at, f"acknowledged: {who}"))

    resolved_at = getattr(alert, "resolved_at", None)

    if resolved_at and getattr(alert, "status", None) == "resolved":
        resolved_by = getattr(alert, "resolved_by", None)
        who = _person(resolved_by) if resolved_by else "automatically"
        entries.append((resolved_at, f"resolved: {who}"))

    entries.sort(key=lambda entry: entry[0])
    entries = entries[-MAX_LINES:]

    return [
        f"{format_offset(moment, start):<6}{escape(text)}"
        for moment, text in entries
    ]


def format_offset(moment, start):
    """Return the time since the alert started: 0s, 5m, 1h 02m, 2d 3h."""

    try:
        seconds = max(int((moment - start).total_seconds()), 0)
    except TypeError:
        return "-"

    if seconds < 60:
        return f"{seconds}s"

    if seconds < 3600:
        return f"{seconds // 60}m"

    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"

    return f"{seconds // 86400}d {seconds % 86400 // 3600}h"


def _assigned_text(alert):
    route = getattr(alert, "route", None)
    assignee = getattr(alert, "assignee", None)
    route_name = getattr(route, "name", None) if route else None

    if route_name and assignee:
        return f'assigned to route "{route_name}", on call: {_person(assignee)}'

    if route_name:
        return f'assigned to route "{route_name}"'

    if assignee:
        return f"on call: {_person(assignee)}"

    return None


def _shelved_text(shelf):
    who = _person(
        getattr(shelf, "shelved_by", None)
        if getattr(shelf, "shelved_by_id", None)
        else None
    )
    ends_at = getattr(shelf, "ends_at", None)

    if ends_at:
        return f"shelved until {timefmt.format_moment(ends_at)}: {who}"

    return f"shelved: {who}"


def _shelves(alert):
    alert_id = getattr(alert, "id", None)

    if not alert_id:
        return []

    return list(
        AlertGroupShelve.select()
        .where(AlertGroupShelve.alert_group == alert_id)
        .order_by(AlertGroupShelve.shelved_at.asc())
    )


def _person(user):
    if not user:
        return "-"

    return str(
        getattr(user, "display_name", None)
        or getattr(user, "username", None)
        or "-"
    )
