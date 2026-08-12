import calendar
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.common import as_utc_aware, as_utc_naive_seconds, utc_now_seconds
from app.modules.db import alerts_repo, heartbeats_repo
from app.modules.db.models import AlertGroup, Heartbeat, HeartbeatInstance
from app.services.alerts.actions import resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.integrations.auth import create_raw_token, hash_token
from app.services.notifications.delivery import notify_alert
from app.services.serializers.common import serialize_utc_datetime

logger = logging.getLogger("oncall.heartbeats")

HEARTBEAT_STATUSES = {"new", "ok", "overdue", "paused"}
HEARTBEAT_MODES = {"interval", "scheduled"}
SCHEDULE_KINDS = {"daily", "weekly", "monthly"}
HEARTBEAT_INSTANCE_STATUSES = {"new", "ok", "overdue", "paused"}
EXPECTED_INSTANCES_MODES = {"none", "static", "auto"}

DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_GRACE_SECONDS = 300


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
    return as_utc_naive_seconds(local_dt)


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


def compute_next_expected_at(heartbeat, now=None):
    """Return the next expected ping deadline before grace is applied."""
    now = as_utc_naive_seconds(now or utc_now_seconds())

    if heartbeat.mode == "scheduled":
        zone = _zone(heartbeat.timezone)
        now_local = as_utc_aware(now).astimezone(zone)
        latest_due = _scheduled_due_local(heartbeat, now_local)
        next_due = _scheduled_next_due_local(heartbeat, latest_due, now_local)
        return _local_to_naive_utc(next_due)

    interval = int(heartbeat.expected_interval_seconds or DEFAULT_INTERVAL_SECONDS)
    anchor = heartbeat.last_seen_at or heartbeat.created_at or now
    return as_utc_naive_seconds(anchor) + timedelta(seconds=interval)


def heartbeat_deadline_at(heartbeat, expected_at=None):
    expected_at = expected_at or heartbeat.next_expected_at or compute_next_expected_at(heartbeat)
    grace = int(heartbeat.grace_period_seconds or 0)
    return expected_at + timedelta(seconds=grace)


def heartbeat_is_overdue(heartbeat, now=None):
    now = as_utc_naive_seconds(now or utc_now_seconds())

    if heartbeat_tracks_instances(heartbeat):
        return False

    if heartbeat.status == "paused" or not heartbeat.enabled or heartbeat.deleted:
        return False

    if heartbeat.mode == "scheduled":
        zone = _zone(heartbeat.timezone)
        now_local = as_utc_aware(now).astimezone(zone)
        due_local = _scheduled_due_local(heartbeat, now_local)
        deadline = _local_to_naive_utc(due_local) + timedelta(seconds=int(heartbeat.grace_period_seconds or 0))

        if now < deadline:
            return False

        due_at = _local_to_naive_utc(due_local)
        last_seen_at = as_utc_naive_seconds(heartbeat.last_seen_at)

        return not last_seen_at or last_seen_at < due_at

    expected_at = heartbeat.next_expected_at or compute_next_expected_at(heartbeat, now=now)
    return now >= heartbeat_deadline_at(heartbeat, expected_at)


def initialize_heartbeat_schedule(heartbeat, now=None):
    if heartbeat_tracks_instances(heartbeat):
        refresh_heartbeat_instance_rollup(heartbeat, now=now)
        return heartbeat

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


def heartbeat_tracks_instances(heartbeat):
    return bool(getattr(heartbeat, "instance_tracking_enabled", False))


def heartbeat_instance_key_name(heartbeat):
    return str(getattr(heartbeat, "instance_key", None) or "instance").strip() or "instance"


def normalize_heartbeat_instance_key(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value[:255]


def extract_heartbeat_instance_key(heartbeat, payload):
    if not isinstance(payload, dict):
        return None

    key_name = heartbeat_instance_key_name(heartbeat)
    candidates = [
        payload.get(key_name),
        payload.get("instance"),
        payload.get("host"),
        payload.get("hostname"),
        payload.get("node"),
    ]

    nested = payload.get("payload")
    if isinstance(nested, dict):
        candidates.extend([
            nested.get(key_name),
            nested.get("instance"),
            nested.get("host"),
            nested.get("hostname"),
            nested.get("node"),
        ])

    for candidate in candidates:
        normalized = normalize_heartbeat_instance_key(candidate)
        if normalized:
            return normalized

    return None


def compute_instance_next_expected_at(heartbeat, instance, now=None):
    now = as_utc_naive_seconds(now or utc_now_seconds())

    if heartbeat.mode == "scheduled":
        return compute_next_expected_at(heartbeat, now=now)

    interval = int(heartbeat.expected_interval_seconds or DEFAULT_INTERVAL_SECONDS)
    anchor = instance.last_seen_at or instance.created_at or now
    return as_utc_naive_seconds(anchor) + timedelta(seconds=interval)


def heartbeat_instance_deadline_at(heartbeat, instance, expected_at=None):
    expected_at = expected_at or instance.next_expected_at or compute_instance_next_expected_at(heartbeat, instance)
    grace = int(heartbeat.grace_period_seconds or 0)
    return expected_at + timedelta(seconds=grace)


def heartbeat_instance_is_overdue(heartbeat, instance, now=None):
    now = as_utc_naive_seconds(now or utc_now_seconds())

    if heartbeat.status == "paused" or not heartbeat.enabled or heartbeat.deleted:
        return False
    if instance.status == "paused" or not instance.enabled:
        return False

    if heartbeat.mode == "scheduled":
        zone = _zone(heartbeat.timezone)
        now_local = as_utc_aware(now).astimezone(zone)
        due_local = _scheduled_due_local(heartbeat, now_local)
        due_at = _local_to_naive_utc(due_local)
        deadline = due_at + timedelta(seconds=int(heartbeat.grace_period_seconds or 0))

        if now < deadline:
            return False

        last_seen_at = as_utc_naive_seconds(instance.last_seen_at)

        return not last_seen_at or last_seen_at < due_at

    expected_at = instance.next_expected_at or compute_instance_next_expected_at(heartbeat, instance, now=now)
    return now >= heartbeat_instance_deadline_at(heartbeat, instance, expected_at)


def refresh_heartbeat_instance_rollup(heartbeat, now=None):
    now = as_utc_naive_seconds(now or utc_now_seconds())
    instances = heartbeats_repo.list_heartbeat_instances(heartbeat.id, enabled_only=True)

    if not heartbeat_tracks_instances(heartbeat):
        return heartbeat

    if heartbeat.status == "paused" or not heartbeat.enabled:
        return heartbeat

    if not instances:
        heartbeat.status = "new"
        heartbeat.last_seen_at = None
        heartbeat.next_expected_at = None
    else:
        overdue = [item for item in instances if item.status == "overdue"]
        seen = [item for item in instances if item.last_seen_at]
        heartbeat.status = "overdue" if overdue else ("ok" if seen else "new")
        heartbeat.last_seen_at = max((item.last_seen_at for item in seen), default=None)
        next_values = [item.next_expected_at for item in instances if item.next_expected_at]
        heartbeat.next_expected_at = min(next_values) if next_values else None

    heartbeat.updated_at = now
    heartbeat.save()
    return heartbeat


def sync_heartbeat_static_instances(heartbeat, expected_instances, now=None):
    now = as_utc_naive_seconds(now or utc_now_seconds())
    desired = []
    seen = set()

    for value in expected_instances or []:
        normalized = normalize_heartbeat_instance_key(value)
        if normalized and normalized not in seen:
            desired.append(normalized)
            seen.add(normalized)

    existing = {item.instance_key: item for item in heartbeats_repo.list_heartbeat_instances(heartbeat.id)}

    for instance_key in desired:
        instance = existing.get(instance_key)
        if instance:
            instance.enabled = True
            instance.auto_discovered = False
            if instance.status == "paused":
                instance.status = "ok" if instance.last_seen_at else "new"
            instance.next_expected_at = compute_instance_next_expected_at(heartbeat, instance, now=now)
            instance.updated_at = now
            instance.save()
        else:
            instance = heartbeats_repo.create_heartbeat_instance(
                heartbeat,
                instance_key,
                status="new",
                enabled=True,
                auto_discovered=False,
                next_expected_at=compute_next_expected_at(heartbeat, now=now),
                created_at=now,
                updated_at=now,
            )

    if heartbeat.expected_instances_mode == "static":
        desired_set = set(desired)
        for instance_key, instance in existing.items():
            if instance_key in desired_set or instance.auto_discovered:
                continue
            if instance.current_alert_group_id:
                continue
            instance.enabled = False
            instance.status = "paused"
            instance.updated_at = now
            instance.save()

    refresh_heartbeat_instance_rollup(heartbeat, now=now)


def heartbeat_expected_instances_from_metadata(heartbeat):
    metadata = heartbeat.metadata or {}
    value = metadata.get("expected_instances")
    return value if isinstance(value, list) else []


def _heartbeat_alert_payload(heartbeat, now):
    last_seen = serialize_utc_datetime(heartbeat.last_seen_at)
    next_expected = serialize_utc_datetime(heartbeat.next_expected_at)
    overdue_since = serialize_utc_datetime(heartbeat.overdue_since or now)

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
    last_seen = serialize_utc_datetime(heartbeat.last_seen_at) or "never"
    expected = serialize_utc_datetime(heartbeat.next_expected_at) or "unknown"
    deadline = (
        serialize_utc_datetime(heartbeat_deadline_at(heartbeat))
        if heartbeat.next_expected_at
        else "unknown"
    )
    return (
        f"Expected heartbeat ping did not arrive. "
        f"Last seen: {last_seen}. Expected at: {expected}. "
        f"Deadline with grace: {deadline}. Detected at: {serialize_utc_datetime(now)}."
    )


def _heartbeat_instance_overdue_message(heartbeat, instance, now):
    last_seen = serialize_utc_datetime(instance.last_seen_at) or "never"
    expected = serialize_utc_datetime(instance.next_expected_at) or "unknown"
    deadline = (
        serialize_utc_datetime(heartbeat_instance_deadline_at(heartbeat, instance))
        if instance.next_expected_at
        else "unknown"
    )
    return (
        f"Expected heartbeat ping did not arrive for instance {instance.instance_key}. "
        f"Last seen: {last_seen}. Expected at: {expected}. "
        f"Deadline with grace: {deadline}. Detected at: {serialize_utc_datetime(now)}."
    )


def _heartbeat_instance_alert_payload(heartbeat, instance, now):
    last_seen = serialize_utc_datetime(instance.last_seen_at)
    next_expected = serialize_utc_datetime(instance.next_expected_at)
    overdue_since = serialize_utc_datetime(instance.overdue_since or now)

    labels = dict(heartbeat.labels or {})
    labels.update({
        "alertname": "HeartbeatInstanceOverdue",
        "heartbeat_id": str(heartbeat.id),
        "heartbeat_uid": str(heartbeat.uid),
        "heartbeat_slug": heartbeat.slug,
        "heartbeat_name": heartbeat.name,
        "heartbeat_instance": instance.instance_key,
        "instance": instance.instance_key,
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
            "instance_tracking_enabled": True,
            "instance_key": heartbeat_instance_key_name(heartbeat),
            "expected_interval_seconds": heartbeat.expected_interval_seconds,
            "grace_period_seconds": heartbeat.grace_period_seconds,
            "schedule_kind": heartbeat.schedule_kind,
            "schedule_time": heartbeat.schedule_time,
            "schedule_weekday": heartbeat.schedule_weekday,
            "schedule_monthday": heartbeat.schedule_monthday,
            "timezone": heartbeat.timezone,
        },
        "instance": {
            "id": instance.id,
            "key": instance.instance_key,
            "last_seen_at": last_seen,
            "next_expected_at": next_expected,
            "overdue_since": overdue_since,
        },
    }

    return {
        "source": "heartbeat",
        "forced_route_id": heartbeat.route_id,
        "forced_team_id": heartbeat.team_id,
        "team_slug": heartbeat.team.slug if heartbeat.team else None,
        "_forced_service_id": heartbeat.service_id,
        "external_id": f"heartbeat:{heartbeat.uid}:instance:{instance.instance_key}",
        "dedup_key": f"heartbeat:{heartbeat.uid}:instance:{instance.instance_key}",
        "title": f"Heartbeat overdue: {heartbeat.name} / {instance.instance_key}",
        "message": _heartbeat_instance_overdue_message(heartbeat, instance, now),
        "severity": heartbeat.severity or "critical",
        "priority_slug": heartbeat.priority_slug or "p2",
        "priority_set_manually": True,
        "labels": labels,
        "annotations": {
            "summary": f"Heartbeat {heartbeat.name} is overdue on {instance.instance_key}",
            "description": _heartbeat_instance_overdue_message(heartbeat, instance, now),
        },
        "payload": payload,
        "status": "firing",
    }


def mark_heartbeat_overdue(heartbeat, now=None):
    """Create or keep the current overdue alert for a heartbeat."""
    now = as_utc_naive_seconds(now or utc_now_seconds())
    status_before = heartbeat.status
    transitioned_to_overdue = status_before != "overdue"

    if not transitioned_to_overdue and heartbeat.current_alert_group_id:
        group = AlertGroup.get_or_none(AlertGroup.id == heartbeat.current_alert_group_id)
        if group and group.status != "resolved":
            return heartbeat, None

    heartbeat.status = "overdue"
    heartbeat.overdue_since = heartbeat.overdue_since or now
    if transitioned_to_overdue:
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

    if transitioned_to_overdue:
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


def mark_heartbeat_instance_overdue(instance, now=None):
    """Create or keep the current overdue alert for one heartbeat producer."""
    now = as_utc_naive_seconds(now or utc_now_seconds())
    heartbeat = instance.heartbeat
    status_before = instance.status
    transitioned_to_overdue = status_before != "overdue"

    if not transitioned_to_overdue and instance.current_alert_group_id:
        group = AlertGroup.get_or_none(AlertGroup.id == instance.current_alert_group_id)
        if group and group.status != "resolved":
            refresh_heartbeat_instance_rollup(heartbeat, now=now)
            return instance, None

    instance.status = "overdue"
    instance.overdue_since = instance.overdue_since or now
    if transitioned_to_overdue:
        instance.last_overdue_at = now
    instance.next_expected_at = compute_instance_next_expected_at(heartbeat, instance, now=now)
    instance.updated_at = now
    instance.save()

    result = upsert_alert(_heartbeat_instance_alert_payload(heartbeat, instance, now))
    group = result.group

    if group:
        instance.current_alert_group = group.id
        instance.save(only=[HeartbeatInstance.current_alert_group])
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="heartbeat_instance_overdue",
            message=f"Heartbeat overdue: {heartbeat.name} / {instance.instance_key}",
        )

    if transitioned_to_overdue:
        heartbeats_repo.record_ping(
            heartbeat,
            event_type="instance_overdue",
            instance_key=instance.instance_key,
            status_before=status_before,
            status_after=instance.status,
            message=f"Heartbeat instance became overdue: {instance.instance_key}",
            alert_group_id=group.id if group else None,
            received_at=now,
        )

    refresh_heartbeat_instance_rollup(heartbeat, now=now)

    if transitioned_to_overdue:
        logger.warning(
            "heartbeat instance became overdue",
            extra={
                "extra": {
                    "event_type": "heartbeat_instance_overdue",
                    "heartbeat_id": heartbeat.id,
                    "heartbeat_uid": str(heartbeat.uid),
                    "heartbeat_instance": instance.instance_key,
                    "team_id": heartbeat.team_id,
                    "route_id": heartbeat.route_id,
                    "service_id": heartbeat.service_id,
                    "alert_group_id": group.id if group else None,
                }
            },
        )

    return instance, group


def _resolve_heartbeat_alert(
    group: AlertGroup,
    *,
    recovery_event_type: str,
    recovery_message: str,
) -> AlertGroup:
    """Resolve a heartbeat alert and complete the resolved delivery flow."""
    had_notification = bool(group.last_notification_at)

    resolved = resolve_alert(
        group.id,
        user_id=None,
        update_messages=False,
    )

    alerts_repo.clear_alert_group_notification(resolved)

    alerts_repo.create_alert_event(
        group_id=resolved.id,
        event_type=recovery_event_type,
        message=recovery_message,
    )

    if had_notification:
        notify_alert(
            resolved,
            event_type="resolved",
        )

    return resolved


def _resolve_current_instance_overdue_alert(
    instance: HeartbeatInstance,
) -> AlertGroup | None:
    if not instance.current_alert_group_id:
        return None

    group = AlertGroup.get_or_none(AlertGroup.id == instance.current_alert_group_id)

    if not group or group.status == "resolved":
        return group

    return _resolve_heartbeat_alert(
        group,
        recovery_event_type="heartbeat_instance_recovered",
        recovery_message=(
            f"Heartbeat recovered: "
            f"{instance.heartbeat.name} / {instance.instance_key}"
        ),
    )


def _resolve_current_overdue_alert(
    heartbeat: Heartbeat,
) -> AlertGroup | None:
    if not heartbeat.current_alert_group_id:
        return None

    group = AlertGroup.get_or_none(AlertGroup.id == heartbeat.current_alert_group_id)

    if not group or group.status == "resolved":
        return group

    return _resolve_heartbeat_alert(
        group,
        recovery_event_type="heartbeat_recovered",
        recovery_message=f"Heartbeat recovered: {heartbeat.name}",
    )


def receive_heartbeat_ping(
    raw_token,
    *,
    payload=None,
    remote_addr=None,
    user_agent=None,
    now=None,
):
    """Record a heartbeat ping and auto-resolve overdue incidents if needed."""
    now = as_utc_naive_seconds(now or utc_now_seconds())
    heartbeat = heartbeats_repo.get_heartbeat_by_token(raw_token)

    if not heartbeat:
        return None, {
            "error": "heartbeat_not_found",
            "message": "Heartbeat token was not found or is disabled.",
        }

    payload = payload or {}

    if heartbeat_tracks_instances(heartbeat):
        instance_key = extract_heartbeat_instance_key(heartbeat, payload)

        if not instance_key:
            return None, {
                "error": "heartbeat_instance_required",
                "message": f"Heartbeat expects instance tracking. Add '{heartbeat_instance_key_name(heartbeat)}' to the ping JSON.",
            }

        instance = heartbeats_repo.get_heartbeat_instance(heartbeat.id, instance_key)

        if not instance:
            if heartbeat.expected_instances_mode == "static":
                expected = set(heartbeat_expected_instances_from_metadata(heartbeat))
                if instance_key not in expected:
                    return None, {
                        "error": "heartbeat_instance_not_expected",
                        "message": f"Instance '{instance_key}' is not expected for this heartbeat.",
                    }

                instance = heartbeats_repo.create_heartbeat_instance(
                    heartbeat,
                    instance_key,
                    status="new",
                    enabled=True,
                    auto_discovered=False,
                    created_at=now,
                    updated_at=now,
                )
            elif heartbeat.expected_instances_mode == "auto":
                instance = heartbeats_repo.create_heartbeat_instance(
                    heartbeat,
                    instance_key,
                    status="new",
                    enabled=True,
                    auto_discovered=True,
                    first_seen_at=now,
                    created_at=now,
                    updated_at=now,
                )
                heartbeats_repo.record_ping(
                    heartbeat,
                    event_type="instance_discovered",
                    instance_key=instance_key,
                    status_before=None,
                    status_after="new",
                    message=f"Heartbeat instance auto-discovered: {instance_key}",
                    payload=payload,
                    remote_addr=remote_addr,
                    user_agent=user_agent,
                    received_at=now,
                )
            else:
                return None, {
                    "error": "heartbeat_instance_not_expected",
                    "message": f"Instance '{instance_key}' is not expected for this heartbeat.",
                }

        if not instance.enabled:
            return None, {
                "error": "heartbeat_instance_disabled",
                "message": f"Instance '{instance_key}' is disabled for this heartbeat.",
            }

        status_before = instance.status
        recovered_group = None

        instance.last_seen_at = now
        instance.last_payload = payload
        instance.last_remote_addr = remote_addr
        instance.last_user_agent = user_agent
        instance.next_expected_at = compute_instance_next_expected_at(heartbeat, instance, now=now)
        instance.updated_at = now

        if instance.status == "overdue":
            if heartbeat.auto_resolve:
                recovered_group = _resolve_current_instance_overdue_alert(instance)
            instance.status = "ok"
            instance.overdue_since = None
            instance.last_recovered_at = now
            instance.current_alert_group = None
        elif instance.status in ("new", "paused"):
            instance.status = "ok" if instance.status != "paused" else "paused"
        else:
            instance.status = "ok"

        instance.save()
        refresh_heartbeat_instance_rollup(heartbeat, now=now)

        heartbeats_repo.record_ping(
            heartbeat,
            event_type="ping" if status_before != "overdue" else "recovery",
            instance_key=instance_key,
            status_before=status_before,
            status_after=instance.status,
            message="Heartbeat instance ping received",
            payload=payload,
            remote_addr=remote_addr,
            user_agent=user_agent,
            alert_group_id=recovered_group.id if recovered_group else None,
            received_at=now,
        )

        logger.info(
            "heartbeat instance ping received",
            extra={
                "extra": {
                    "event_type": "heartbeat_ping",
                    "heartbeat_id": heartbeat.id,
                    "heartbeat_uid": str(heartbeat.uid),
                    "heartbeat_instance": instance_key,
                    "status_before": status_before,
                    "status_after": instance.status,
                    "team_id": heartbeat.team_id,
                    "service_id": heartbeat.service_id,
                    "recovered_alert_group_id": recovered_group.id if recovered_group else None,
                }
            },
        )

        return heartbeat, None

    status_before = heartbeat.status
    recovered_group = None

    heartbeat.last_seen_at = now
    heartbeat.last_payload = payload
    heartbeat.last_remote_addr = remote_addr
    heartbeat.last_user_agent = user_agent
    heartbeat.next_expected_at = compute_next_expected_at(heartbeat, now=now)
    heartbeat.updated_at = now

    if heartbeat.status == "overdue":
        if heartbeat.auto_resolve:
            recovered_group = _resolve_current_overdue_alert(heartbeat)
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
        payload=payload,
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
    now = as_utc_naive_seconds(now or utc_now_seconds())
    result = {
        "processed": 0,
        "overdue": 0,
        "unchanged": 0,
        "failed": 0,
        "instances_processed": 0,
        "instances_overdue": 0,
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

    instance_candidates = heartbeats_repo.list_due_heartbeat_instance_candidates(
        now,
        limit=limit,
        team_ids=team_ids,
    )

    for instance in instance_candidates:
        result["instances_processed"] += 1
        try:
            heartbeat = instance.heartbeat
            if heartbeat_instance_is_overdue(heartbeat, instance, now=now):
                before = instance.status
                mark_heartbeat_instance_overdue(instance, now=now)
                if before != "overdue":
                    result["instances_overdue"] += 1
                    result["overdue"] += 1
                else:
                    result["unchanged"] += 1
            else:
                instance.next_expected_at = compute_instance_next_expected_at(heartbeat, instance, now=now)
                instance.save(only=[HeartbeatInstance.next_expected_at])
                refresh_heartbeat_instance_rollup(heartbeat, now=now)
                result["unchanged"] += 1
        except Exception:
            logger.exception(
                "heartbeat instance overdue check failed",
                extra={
                    "extra": {
                        "heartbeat_instance_id": getattr(instance, "id", None),
                        "heartbeat_id": getattr(instance, "heartbeat_id", None),
                    }
                },
            )
            result["failed"] += 1

    expire_auto_discovered_instances(now=now, team_ids=team_ids)

    return result


def expire_auto_discovered_instances(now=None, team_ids=None):
    now = as_utc_naive_seconds(now or utc_now_seconds())
    candidates = heartbeats_repo.list_heartbeats(team_ids=team_ids, enabled_only=True)
    expired = 0

    for heartbeat in candidates:
        if not heartbeat_tracks_instances(heartbeat):
            continue
        ttl_days = heartbeat.auto_discovery_ttl_days
        if not ttl_days:
            continue

        cutoff = now - timedelta(days=int(ttl_days))
        changed = False
        for instance in heartbeats_repo.list_heartbeat_instances(heartbeat.id, enabled_only=True):
            if not instance.auto_discovered:
                continue
            if instance.current_alert_group_id or instance.status == "overdue":
                continue
            last_seen = instance.last_seen_at or instance.first_seen_at or instance.created_at
            if last_seen and last_seen < cutoff:
                instance.enabled = False
                instance.status = "paused"
                instance.updated_at = now
                instance.save()
                expired += 1
                changed = True
                heartbeats_repo.record_ping(
                    heartbeat,
                    event_type="instance_expired",
                    instance_key=instance.instance_key,
                    status_before="ok",
                    status_after="paused",
                    message=f"Auto-discovered heartbeat instance expired: {instance.instance_key}",
                    received_at=now,
                )
        if changed:
            refresh_heartbeat_instance_rollup(heartbeat, now=now)

    return expired

def pause_heartbeat(heartbeat, now=None):
    now = as_utc_naive_seconds(now or utc_now_seconds())
    before = heartbeat.status
    heartbeat.status = "paused"
    heartbeat.updated_at = now
    heartbeat.save()

    if heartbeat_tracks_instances(heartbeat):
        for instance in heartbeats_repo.list_heartbeat_instances(heartbeat.id, enabled_only=True):
            instance.status = "paused"
            instance.updated_at = now
            instance.save()

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
    now = as_utc_naive_seconds(now or utc_now_seconds())
    before = heartbeat.status

    if heartbeat_tracks_instances(heartbeat):
        for instance in heartbeats_repo.list_heartbeat_instances(heartbeat.id, enabled_only=True):
            instance.status = "ok" if instance.last_seen_at else "new"
            instance.next_expected_at = compute_instance_next_expected_at(heartbeat, instance, now=now)
            instance.updated_at = now
            instance.save()
        refresh_heartbeat_instance_rollup(heartbeat, now=now)
    else:
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
