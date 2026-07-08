import calendar
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.modules.common import as_utc_aware
from app.modules.db import alerts_repo, heartbeats_repo
from app.modules.db.models import AlertGroup, Heartbeat
from app.services.alerts.actions import resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.integrations.auth import create_raw_token, hash_token

logger = logging.getLogger("oncall.heartbeats")

HEARTBEAT_STATUSES = {"new", "ok", "overdue", "paused"}
HEARTBEAT_MODES = {"interval", "scheduled"}
SCHEDULE_KINDS = {"daily", "weekly", "monthly"}

DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_GRACE_SECONDS = 300


def _utcnow():
    return datetime.utcnow().replace(microsecond=0)


def _as_naive_utc(value):
    aware = as_utc_aware(value)

    if aware is None:
        return None

    return aware.replace(tzinfo=None, microsecond=0)


def _zone(name):
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _parse_schedule_time(value):
    value = str(value or "").strip()
    hour_text, minute_text = (value.split(":", 1) + ["0"])[:2]
    hour = max(0, min(23, int(hour_text)))
    minute = max(0, min(59, int(minute_text)))
    return time(hour=hour, minute=minute)


def _local_to_naive_utc(local_dt):
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _monthly_date(year, month, day):
    last_day = calendar.monthrange(year, month)[1]
    return min(max(1, int(day or 1)), last_day)


def _previous_month(year, month):
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _next_month(year, month):
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _scheduled_due_local(heartbeat, now_local):
    schedule_time = _parse_schedule_time(heartbeat.schedule_time or "00:00")
    kind = heartbeat.schedule_kind or "daily"

    if kind == "weekly":
        weekday = int(heartbeat.schedule_weekday or 0)
        weekday = max(0, min(6, weekday))
        days_since = (now_local.weekday() - weekday) % 7
        due_date = (now_local - timedelta(days=days_since)).date()
        due = datetime.combine(due_date, schedule_time, tzinfo=now_local.tzinfo)
        if due > now_local:
            due -= timedelta(days=7)
        return due

    if kind == "monthly":
        day = _monthly_date(now_local.year, now_local.month, heartbeat.schedule_monthday or 1)
        due = datetime.combine(
            now_local.replace(day=day).date(),
            schedule_time,
            tzinfo=now_local.tzinfo,
        )
        if due > now_local:
            year, month = _previous_month(now_local.year, now_local.month)
            day = _monthly_date(year, month, heartbeat.schedule_monthday or 1)
            due = datetime.combine(
                datetime(year, month, day).date(),
                schedule_time,
                tzinfo=now_local.tzinfo,
            )
        return due

    due = datetime.combine(now_local.date(), schedule_time, tzinfo=now_local.tzinfo)
    if due > now_local:
        due -= timedelta(days=1)
    return due


def _scheduled_next_due_local(heartbeat, latest_due_local, now_local):
    kind = heartbeat.schedule_kind or "daily"

    if kind == "weekly":
        candidate = latest_due_local + timedelta(days=7)
        while candidate <= now_local:
            candidate += timedelta(days=7)
        return candidate

    if kind == "monthly":
        candidate = latest_due_local
        while candidate <= now_local:
            year, month = _next_month(candidate.year, candidate.month)
            day = _monthly_date(year, month, heartbeat.schedule_monthday or 1)
            candidate = candidate.replace(year=year, month=month, day=day)
        return candidate

    candidate = latest_due_local + timedelta(days=1)
    while candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate


def _scheduled_window_start_local(heartbeat, due_local):
    kind = heartbeat.schedule_kind or "daily"

    if kind == "weekly":
        return due_local - timedelta(days=7)

    if kind == "monthly":
        year, month = _previous_month(due_local.year, due_local.month)
        day = _monthly_date(year, month, heartbeat.schedule_monthday or 1)
        return due_local.replace(year=year, month=month, day=day)

    return due_local - timedelta(days=1)


def compute_next_expected_at(heartbeat, now=None):
    """Return the next expected ping deadline before grace is applied."""
    now = _as_naive_utc(now or _utcnow())

    if heartbeat.mode == "scheduled":
        zone = _zone(heartbeat.timezone)
        now_local = now.replace(tzinfo=timezone.utc).astimezone(zone)
        latest_due = _scheduled_due_local(heartbeat, now_local)
        next_due = _scheduled_next_due_local(heartbeat, latest_due, now_local)
        return _local_to_naive_utc(next_due)

    interval = int(heartbeat.expected_interval_seconds or DEFAULT_INTERVAL_SECONDS)
    anchor = heartbeat.last_seen_at or heartbeat.created_at or now
    return _as_naive_utc(anchor) + timedelta(seconds=interval)


def heartbeat_deadline_at(heartbeat, expected_at=None):
    expected_at = expected_at or heartbeat.next_expected_at or compute_next_expected_at(heartbeat)
    grace = int(heartbeat.grace_period_seconds or 0)
    return expected_at + timedelta(seconds=grace)


def heartbeat_is_overdue(heartbeat, now=None):
    now = _as_naive_utc(now or _utcnow())

    if heartbeat.status == "paused" or not heartbeat.enabled or heartbeat.deleted:
        return False

    if heartbeat.mode == "scheduled":
        zone = _zone(heartbeat.timezone)
        now_local = now.replace(tzinfo=timezone.utc).astimezone(zone)
        due_local = _scheduled_due_local(heartbeat, now_local)
        deadline = _local_to_naive_utc(due_local) + timedelta(seconds=int(heartbeat.grace_period_seconds or 0))

        if now < deadline:
            return False

        window_start = _local_to_naive_utc(_scheduled_window_start_local(heartbeat, due_local))
        return not heartbeat.last_seen_at or heartbeat.last_seen_at < window_start

    expected_at = heartbeat.next_expected_at or compute_next_expected_at(heartbeat, now=now)
    return now >= heartbeat_deadline_at(heartbeat, expected_at)


def initialize_heartbeat_schedule(heartbeat, now=None):
    heartbeat.next_expected_at = compute_next_expected_at(heartbeat, now=now)
    heartbeat.save(only=[Heartbeat.next_expected_at])
    return heartbeat


def generate_heartbeat_token():
    raw = create_raw_token()
    return raw, raw[:12], hash_token(raw)


def build_ping_url(raw_token, base_url=None):
    path = f"/api/heartbeats/ping/{raw_token}"
    if not base_url:
        return path
    return str(base_url).rstrip("/") + path


def _heartbeat_alert_payload(heartbeat, now):
    last_seen = heartbeat.last_seen_at.isoformat() + "Z" if heartbeat.last_seen_at else None
    next_expected = heartbeat.next_expected_at.isoformat() + "Z" if heartbeat.next_expected_at else None
    overdue_since = heartbeat.overdue_since.isoformat() + "Z" if heartbeat.overdue_since else now.isoformat() + "Z"

    labels = dict(heartbeat.labels or {})
    labels.update({
        "alertname": "HeartbeatOverdue",
        "heartbeat_id": str(heartbeat.id),
        "heartbeat_uid": str(heartbeat.uid),
        "heartbeat_slug": heartbeat.slug,
        "heartbeat_name": heartbeat.name,
        "team": heartbeat.team.slug if heartbeat.team else None,
        "service_id": str(heartbeat.service_id or ""),
        "source": "heartbeat",
    })

    payload = {
        "heartbeat": {
            "id": heartbeat.id,
            "uid": str(heartbeat.uid),
            "name": heartbeat.name,
            "slug": heartbeat.slug,
            "mode": heartbeat.mode,
            "expected_interval_seconds": heartbeat.expected_interval_seconds,
            "grace_period_seconds": heartbeat.grace_period_seconds,
            "schedule_kind": heartbeat.schedule_kind,
            "schedule_time": heartbeat.schedule_time,
            "schedule_weekday": heartbeat.schedule_weekday,
            "schedule_monthday": heartbeat.schedule_monthday,
            "timezone": heartbeat.timezone,
            "last_seen_at": last_seen,
            "next_expected_at": next_expected,
            "overdue_since": overdue_since,
        }
    }

    return {
        "source": "heartbeat",
        "forced_route_id": heartbeat.route_id,
        "forced_team_id": heartbeat.team_id,
        "team_slug": heartbeat.team.slug if heartbeat.team else None,
        "_forced_service_id": heartbeat.service_id,
        "external_id": f"heartbeat:{heartbeat.uid}",
        "dedup_key": f"heartbeat:{heartbeat.uid}",
        "title": f"Heartbeat overdue: {heartbeat.name}",
        "message": _heartbeat_overdue_message(heartbeat, now),
        "severity": heartbeat.severity or "critical",
        "priority_slug": heartbeat.priority_slug or "p2",
        "priority_set_manually": True,
        "labels": labels,
        "annotations": {
            "summary": f"Heartbeat {heartbeat.name} is overdue",
            "description": _heartbeat_overdue_message(heartbeat, now),
        },
        "payload": payload,
        "status": "firing",
    }


def _heartbeat_overdue_message(heartbeat, now):
    last_seen = heartbeat.last_seen_at.isoformat() + "Z" if heartbeat.last_seen_at else "never"
    expected = heartbeat.next_expected_at.isoformat() + "Z" if heartbeat.next_expected_at else "unknown"
    deadline = heartbeat_deadline_at(heartbeat).isoformat() + "Z" if heartbeat.next_expected_at else "unknown"
    return (
        f"Expected heartbeat ping did not arrive. "
        f"Last seen: {last_seen}. Expected at: {expected}. "
        f"Deadline with grace: {deadline}. Detected at: {now.isoformat()}Z."
    )


def mark_heartbeat_overdue(heartbeat, now=None):
    """Create or keep the current overdue alert for a heartbeat."""
    now = _as_naive_utc(now or _utcnow())
    status_before = heartbeat.status

    if status_before == "overdue" and heartbeat.current_alert_group_id:
        group = AlertGroup.get_or_none(AlertGroup.id == heartbeat.current_alert_group_id)
        if group and group.status != "resolved":
            return heartbeat, None

    heartbeat.status = "overdue"
    heartbeat.overdue_since = heartbeat.overdue_since or now
    heartbeat.last_overdue_at = now
    heartbeat.updated_at = now
    heartbeat.next_expected_at = compute_next_expected_at(heartbeat, now=now)
    heartbeat.save()

    result = upsert_alert(_heartbeat_alert_payload(heartbeat, now))
    group = result.group

    if group:
        heartbeat.current_alert_group = group.id
        heartbeat.save(only=[Heartbeat.current_alert_group])
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="heartbeat_overdue",
            message=f"Heartbeat overdue: {heartbeat.name}",
        )

    heartbeats_repo.record_ping(
        heartbeat,
        event_type="overdue",
        status_before=status_before,
        status_after=heartbeat.status,
        message="Heartbeat became overdue",
        alert_group_id=group.id if group else None,
        received_at=now,
    )

    logger.warning(
        "heartbeat became overdue",
        extra={
            "extra": {
                "event_type": "heartbeat_overdue",
                "heartbeat_id": heartbeat.id,
                "heartbeat_uid": str(heartbeat.uid),
                "team_id": heartbeat.team_id,
                "route_id": heartbeat.route_id,
                "service_id": heartbeat.service_id,
                "alert_group_id": group.id if group else None,
            }
        },
    )

    return heartbeat, group


def _resolve_current_overdue_alert(heartbeat, now):
    if not heartbeat.current_alert_group_id:
        return None

    group = AlertGroup.get_or_none(AlertGroup.id == heartbeat.current_alert_group_id)

    if not group or group.status == "resolved":
        return group

    resolved = resolve_alert(group.id, user_id=None)
    alerts_repo.create_alert_event(
        group_id=resolved.id,
        event_type="heartbeat_recovered",
        message=f"Heartbeat recovered: {heartbeat.name}",
    )
    return resolved


def receive_heartbeat_ping(
    raw_token,
    *,
    payload=None,
    remote_addr=None,
    user_agent=None,
    now=None,
):
    """Record a heartbeat ping and auto-resolve an overdue incident if needed."""
    now = _as_naive_utc(now or _utcnow())
    heartbeat = heartbeats_repo.get_heartbeat_by_token(raw_token)

    if not heartbeat:
        return None, {
            "error": "heartbeat_not_found",
            "message": "Heartbeat token was not found or is disabled.",
        }

    status_before = heartbeat.status
    recovered_group = None

    heartbeat.last_seen_at = now
    heartbeat.last_payload = payload or {}
    heartbeat.last_remote_addr = remote_addr
    heartbeat.last_user_agent = user_agent
    heartbeat.next_expected_at = compute_next_expected_at(heartbeat, now=now)
    heartbeat.updated_at = now

    if heartbeat.status == "overdue":
        if heartbeat.auto_resolve:
            recovered_group = _resolve_current_overdue_alert(heartbeat, now)
        heartbeat.status = "ok"
        heartbeat.overdue_since = None
        heartbeat.last_recovered_at = now
        heartbeat.current_alert_group = None
    elif heartbeat.status in ("new", "paused"):
        heartbeat.status = "ok" if heartbeat.status != "paused" else "paused"
    else:
        heartbeat.status = "ok"

    heartbeat.save()

    heartbeats_repo.record_ping(
        heartbeat,
        event_type="ping" if status_before != "overdue" else "recovery",
        status_before=status_before,
        status_after=heartbeat.status,
        message="Heartbeat ping received",
        payload=payload or {},
        remote_addr=remote_addr,
        user_agent=user_agent,
        alert_group_id=recovered_group.id if recovered_group else None,
        received_at=now,
    )

    logger.info(
        "heartbeat ping received",
        extra={
            "extra": {
                "event_type": "heartbeat_ping",
                "heartbeat_id": heartbeat.id,
                "heartbeat_uid": str(heartbeat.uid),
                "status_before": status_before,
                "status_after": heartbeat.status,
                "team_id": heartbeat.team_id,
                "service_id": heartbeat.service_id,
                "recovered_alert_group_id": recovered_group.id if recovered_group else None,
            }
        },
    )

    return heartbeat, None


def process_overdue_heartbeats(now=None, limit=100, team_ids=None):
    """Check due heartbeat candidates and open overdue alerts."""
    now = _as_naive_utc(now or _utcnow())
    result = {
        "processed": 0,
        "overdue": 0,
        "unchanged": 0,
        "failed": 0,
    }

    candidates = heartbeats_repo.list_due_heartbeat_candidates(now, limit=limit, team_ids=team_ids)

    for heartbeat in candidates:
        result["processed"] += 1
        try:
            if heartbeat_is_overdue(heartbeat, now=now):
                before = heartbeat.status
                mark_heartbeat_overdue(heartbeat, now=now)
                if before != "overdue":
                    result["overdue"] += 1
                else:
                    result["unchanged"] += 1
            else:
                heartbeat.next_expected_at = compute_next_expected_at(heartbeat, now=now)
                heartbeat.save(only=[Heartbeat.next_expected_at])
                result["unchanged"] += 1
        except Exception:
            logger.exception(
                "heartbeat overdue check failed",
                extra={"extra": {"heartbeat_id": getattr(heartbeat, "id", None)}},
            )
            result["failed"] += 1

    return result


def pause_heartbeat(heartbeat, now=None):
    now = _as_naive_utc(now or _utcnow())
    before = heartbeat.status
    heartbeat.status = "paused"
    heartbeat.updated_at = now
    heartbeat.save()
    heartbeats_repo.record_ping(
        heartbeat,
        event_type="paused",
        status_before=before,
        status_after="paused",
        message="Heartbeat paused",
        received_at=now,
    )
    return heartbeat


def resume_heartbeat(heartbeat, now=None):
    now = _as_naive_utc(now or _utcnow())
    before = heartbeat.status
    heartbeat.status = "ok" if heartbeat.last_seen_at else "new"
    heartbeat.next_expected_at = compute_next_expected_at(heartbeat, now=now)
    heartbeat.updated_at = now
    heartbeat.save()
    heartbeats_repo.record_ping(
        heartbeat,
        event_type="resumed",
        status_before=before,
        status_after=heartbeat.status,
        message="Heartbeat resumed",
        received_at=now,
    )
    return heartbeat
