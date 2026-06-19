import hashlib
from datetime import datetime, timezone


def event_uid(event):
    parts = [
        "incidentrelay",
        str(event.get("team_id") or "team"),
        str(event.get("rotation_id") or "rotation"),
        str(event.get("layer_id") or event.get("override_id") or "shift"),
        str(event.get("user_id") or "user"),
        str(event.get("start") or "start"),
    ]

    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return f"{digest}@incidentrelay"


def event_href(team_id, event):
    return f"/caldav/calendars/teams/{team_id}/{event_uid(event)}.ics"


def event_etag(event):
    raw = "|".join([
        str(event.get("team_id")),
        str(event.get("rotation_id")),
        str(event.get("layer_id") or event.get("override_id")),
        str(event.get("user_id")),
        str(event.get("start")),
        str(event.get("end")),
        str(event.get("display_name") or event.get("username")),
    ])

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f'"{digest}"'


def build_event_ics(event):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//IncidentRelay//CalDAV//EN",
        "CALSCALE:GREGORIAN",
    ]

    lines.extend(build_vevent_lines(event))

    lines.append("END:VCALENDAR")

    return "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n"


def parse_datetime(value):
    text = str(value or "")

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    parsed = datetime.fromisoformat(text)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def format_datetime(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    value = value.astimezone(timezone.utc)
    return value.strftime("%Y%m%dT%H%M%SZ")


def ics_escape(value):
    text = str(value or "")

    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_ics_line(line):
    if len(line) <= 75:
        return line

    chunks = [line[:75]]
    cursor = 75

    while cursor < len(line):
        chunks.append(" " + line[cursor:cursor + 74])
        cursor += 74

    return "\r\n".join(chunks)


def build_calendar_ics(calendar_name, events):
    """Build one VCALENDAR with many VEVENT objects."""
    now = datetime.now(timezone.utc)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//IncidentRelay//On-call Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(calendar_name)}",
        "X-WR-TIMEZONE:UTC",
        "REFRESH-INTERVAL;VALUE=DURATION:PT15M",
        "X-PUBLISHED-TTL:PT15M",
    ]

    for event in events:
        lines.extend(build_vevent_lines(event, now))

    lines.append("END:VCALENDAR")

    return "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n"


def build_vevent_lines(event, dtstamp=None):
    """Build VEVENT lines without VCALENDAR wrapper."""
    dtstamp = dtstamp or datetime.now(timezone.utc)

    start = parse_datetime(event.get("start"))
    end = parse_datetime(event.get("end"))

    user_label = (
        event.get("display_name")
        or event.get("username")
        or f"user-{event.get('user_id')}"
    )

    team_name = event.get("team_name") or event.get("team_slug") or "team"
    rotation_name = event.get("rotation_name") or f"rotation #{event.get('rotation_id')}"

    description_lines = [
        f"Team: {team_name}",
        f"Rotation: {rotation_name}",
    ]

    if event.get("layer_name"):
        description_lines.append(f"Layer: {event.get('layer_name')}")

    if event.get("type"):
        description_lines.append(f"Type: {event.get('type')}")

    if event.get("reason"):
        description_lines.append(f"Reason: {event.get('reason')}")

    return [
        "BEGIN:VEVENT",
        f"UID:{event_uid(event)}",
        f"DTSTAMP:{format_datetime(dtstamp)}",
        f"DTSTART:{format_datetime(start)}",
        f"DTEND:{format_datetime(end)}",
        f"SUMMARY:{ics_escape('On-call: ' + user_label)}",
        f"DESCRIPTION:{ics_escape(chr(10).join(description_lines))}",
        f"LOCATION:{ics_escape(team_name)}",
        "TRANSP:OPAQUE",
        "END:VEVENT",
    ]
