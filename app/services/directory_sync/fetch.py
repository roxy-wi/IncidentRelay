"""Collect and validate a complete snapshot before changing any IR resources."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from email_validator import EmailNotValidError, validate_email

from app.modules.common import utc_now
from app.services.directory_sync.config import SyncError, map_fields, path_value


def identity(value, label):
    """Require an opaque nonempty stable identity without truncation."""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise SyncError(f"{label}: a stable ID is required")
    value = str(value).strip()
    if not value or len(value) > 255:
        raise SyncError(f"{label}: ID must contain 1–255 characters")
    return value


def instant(value):
    """Require an explicit timezone and store normalized UTC timestamps."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone missing")
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, AttributeError, ValueError) as error:
        raise SyncError("Mapped timestamps must be ISO 8601 with a timezone") from error


def iso(value):
    return value.isoformat() + "Z"


def window(config, now=None):
    now = now or utc_now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = start.month - 1 + config.horizon_months
    end = start.replace(year=start.year + month // 12, month=month % 12 + 1)
    return {"from": iso(start), "to": iso(end)}


def collection(data, definition):
    values = path_value(data, definition.path)
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise SyncError(f"Collection {definition.path} is missing or is not an array")
    return [(item, map_fields(item, definition.fields)) for item in values]


def flag(value):
    if value is None:
        return False
    if not isinstance(value, bool):
        raise SyncError("Boolean mappings must resolve to JSON true or false")
    return value


def fetch_snapshot(client):
    """Fetch teams, all referenced people, schedules and concrete shifts."""
    config = client.config
    context = window(config)
    teams, people, schedules, shifts = {}, {}, set(), set()

    def person(raw, team_id):
        key = identity(raw.get("id"), "person")
        previous = people.get(key, {})
        merged = {**previous, **{k: v for k, v in raw.items() if v is not None}}
        merged.update(id=key, team_id=team_id, inactive=flag(raw.get("inactive")) or previous.get("inactive", False))
        people[key] = merged
        return key

    for raw in client.records("teams", context):
        if config.team_filter and not path_value(raw, config.team_filter):
            continue
        team = map_fields(raw, config.team_fields)
        team_id = identity(team.get("id"), "team")
        if team_id in teams:
            raise SyncError("Duplicate team ID in API response")
        team["id"] = team_id
        team_context = {**context, "team_id": team_id}
        detail = raw
        if "team" in config.operations:
            response = client.request("team", team_context)
            detail = path_value(response, config.operations["team"].items)
            if not isinstance(detail, dict):
                raise SyncError("team: expected an object")
            team.update(map_fields(detail, config.detail_fields))
        if not team.get("name") or len(str(team["name"])) > 255:
            raise SyncError("Team name is missing or too long")
        if not isinstance(team["name"], str):
            raise SyncError("Team name must be a string")
        team["enabled"] = flag(team.get("enabled", True))
        team["members"] = [person(member, team_id) for _, member in collection(detail, config.members)]
        team["responsible"] = None
        if config.responsible:
            responsible = path_value(detail, config.responsible.path)
            if responsible:
                mapped = map_fields(responsible, config.responsible.fields)
                if mapped.get("id"):
                    team["responsible"] = person(mapped, team_id)
        team["schedules"] = []
        for number, (_, schedule) in enumerate(collection(detail, config.schedules), 1):
            schedule["id"] = identity(schedule.get("id"), "schedule")
            if schedule["id"] in schedules:
                raise SyncError("Duplicate schedule ID in API response")
            schedules.add(schedule["id"])
            schedule["name"] = schedule.get("name") or f"{team['name']} / {number}"
            if not isinstance(schedule["name"], str) or len(schedule["name"]) > 255:
                raise SyncError("Schedule name must contain 1–255 characters")
            schedule["timezone"] = schedule.get("timezone") or "UTC"
            try:
                ZoneInfo(schedule["timezone"])
            except (ZoneInfoNotFoundError, TypeError) as error:
                raise SyncError("Unknown schedule timezone") from error
            team["schedules"].append(schedule)
        own_schedules = {item["id"] for item in team["schedules"]}
        team["shifts"] = []
        for raw_shift in client.records("shifts", team_context):
            shift = map_fields(raw_shift, config.shift_fields)
            shift["id"] = identity(shift.get("id"), "shift")
            shift["schedule_id"] = identity(shift.get("schedule_id"), "shift schedule")
            if shift["id"] in shifts or shift["schedule_id"] not in own_schedules:
                raise SyncError("Duplicate shift ID or unknown schedule")
            shifts.add(shift["id"])
            start, end = instant(shift.get("start")), instant(shift.get("end"))
            if end <= start or start >= instant(context["to"]) or end <= instant(context["from"]):
                raise SyncError("Shift interval is invalid or outside the requested window")
            shift.update(start=iso(start), end=iso(end),
                         unavailable=flag(shift.get("unavailable")) or flag(shift.get("inactive")))
            shift["user_id"] = person({"id": shift.get("user_id"), "inactive": flag(shift.get("inactive"))}, team_id)
            shift["replacements"] = []
            replacement_ids = set()
            for _, replacement in collection(raw_shift, config.replacements):
                replacement["id"] = identity(replacement.get("id"), "replacement")
                if replacement["id"] in replacement_ids:
                    raise SyncError("Duplicate replacement ID")
                replacement_ids.add(replacement["id"])
                rs, re = instant(replacement.get("start")), instant(replacement.get("end"))
                if rs < start or re > end or re <= rs:
                    raise SyncError("Replacement must lie inside its shift")
                try:
                    if isinstance(replacement.get("precedence"), (bool, float)):
                        raise ValueError("Non-integer precedence")
                    replacement["precedence"] = int(replacement["precedence"])
                except (KeyError, TypeError, ValueError) as error:
                    raise SyncError("Replacement precedence must be an integer") from error
                replacement.update(start=iso(rs), end=iso(re), inactive=flag(replacement.get("inactive")))
                replacement["user_id"] = person({"id": replacement.get("user_id"), "inactive": replacement["inactive"]}, team_id)
                shift["replacements"].append(replacement)
            team["shifts"].append(shift)
        teams[team_id] = team

    profiles = {}
    if "user" in config.operations and config.user_fetch == "all":
        for record in client.records("user", context):
            profile = map_fields(record, config.user_fields)
            key = identity(profile.get("id"), "profile")
            if key in profiles:
                raise SyncError("Duplicate user profile ID")
            profiles[key] = profile
    for person_id, user in people.items():
        if "user" in config.operations:
            if config.user_fetch == "all":
                if person_id not in profiles:
                    raise SyncError("A referenced person is missing from the user directory")
                user.update({key: value for key, value in profiles[person_id].items() if value is not None})
            else:
                user.update(fetch_profile(client, person_id, user["team_id"], context))
        email = str(user.get("email") or "").strip().lower()
        try:
            email = validate_email(email, check_deliverability=False).normalized.lower()
        except EmailNotValidError as error:
            raise SyncError("Every referenced person needs a valid email for identity matching") from error
        user["email"] = email
        user["inactive"] = flag(user.get("inactive"))
    emails = [user["email"] for user in people.values()]
    if len(emails) != len(set(emails)):
        raise SyncError("Different external people share the same email")
    return {**context, "teams": list(teams.values()), "users": list(people.values())}


def fetch_profile(client, person_id, team_id, context):
    """Fetch one profile without assuming a specific endpoint or response envelope."""
    config = client.config
    op = config.operations["user"]
    person_context = {**context, "user_id": person_id, "team_id": team_id}
    data = client.request("user", person_context)
    record = path_value(data, op.items)
    if isinstance(record, list):
        if len(record) != 1:
            raise SyncError("user: expected exactly one profile")
        record = record[0]
    if not isinstance(record, dict):
        raise SyncError("user: profile is missing")
    profile = map_fields(record, config.user_fields)
    if profile.get("id") and identity(profile["id"], "profile") != person_id:
        raise SyncError("user: profile ID does not match the requested person")
    return {key: value for key, value in profile.items() if value is not None and (key != "name" or value)}


def fetch_current(client, schedule_ids):
    """Require exactly one valid answer per requested slot, including vacant slots."""
    result = []
    size = 1 if client.config.current_fetch == "per_schedule" else 500
    for start in range(0, len(schedule_ids), size):
        ids = schedule_ids[start:start + size]
        if client.config.current_fetch == "per_schedule":
            data = client.request("current", {"schedule_id": ids[0], "schedule_ids": ids})
            value = path_value(data, client.config.operations["current"].items)
            rows = value if isinstance(value, list) else [value]
        else:
            rows = client.records("current", {"schedule_ids": ids})
        mapped = [map_fields(row, client.config.current_fields) for row in rows]
        returned = [identity(item.get("id"), "current schedule") for item in mapped]
        if len(returned) != len(set(returned)) or set(returned) != set(ids):
            raise SyncError("current: response must include every requested schedule exactly once")
        for row in mapped:
            row["id"] = identity(row.get("id"), "current schedule")
            if row.get("status") not in {"active", "gap", "unavailable", "ambiguous"}:
                raise SyncError("current: unknown status")
            if row["status"] == "active":
                row["user_id"] = identity(row.get("user_id"), "current person")
            if row.get("valid_until"):
                instant(row["valid_until"])
        result.extend(mapped)
    return result
