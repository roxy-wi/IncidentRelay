from datetime import datetime


def isoformat(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    return str(value)


def serialize_heartbeat(item, *, include_token=False, raw_token=None, base_url=None, pings=None):
    from app.services.heartbeats.service import build_ping_url, heartbeat_deadline_at

    deadline_at = None
    if item.next_expected_at:
        deadline_at = heartbeat_deadline_at(item)

    payload = {
        "id": item.id,
        "uid": str(item.uid),
        "name": item.name,
        "slug": item.slug,
        "description": item.description,
        "group_id": item.group_id,
        "group_name": item.group.name if item.group_id and item.group else None,
        "team_id": item.team_id,
        "team_name": item.team.name if item.team_id and item.team else None,
        "team_slug": item.team.slug if item.team_id and item.team else None,
        "service_id": item.service_id,
        "service_name": item.service.name if item.service_id and item.service else None,
        "service_slug": item.service.slug if item.service_id and item.service else None,
        "route_id": item.route_id,
        "route_name": item.route.name if item.route_id and item.route else None,
        "mode": item.mode,
        "expected_interval_seconds": item.expected_interval_seconds,
        "grace_period_seconds": item.grace_period_seconds,
        "schedule_kind": item.schedule_kind,
        "schedule_time": item.schedule_time,
        "schedule_weekday": item.schedule_weekday,
        "schedule_monthday": item.schedule_monthday,
        "timezone": item.timezone,
        "status": item.status,
        "enabled": item.enabled,
        "auto_resolve": item.auto_resolve,
        "severity": item.severity,
        "priority_slug": item.priority_slug,
        "token_prefix": item.token_prefix,
        "last_seen_at": isoformat(item.last_seen_at),
        "next_expected_at": isoformat(item.next_expected_at),
        "deadline_at": isoformat(deadline_at),
        "overdue_since": isoformat(item.overdue_since),
        "last_overdue_at": isoformat(item.last_overdue_at),
        "last_recovered_at": isoformat(item.last_recovered_at),
        "current_alert_group_id": item.current_alert_group_id,
        "labels": item.labels or {},
        "metadata": item.metadata or {},
        "created_by_id": item.created_by_id,
        "created_at": isoformat(item.created_at),
        "updated_at": isoformat(item.updated_at),
    }

    if include_token and raw_token:
        payload["token"] = raw_token
        payload["ping_url"] = build_ping_url(raw_token, base_url=base_url)
    elif item.token_prefix:
        payload["ping_url_hint"] = f"/api/heartbeats/ping/{item.token_prefix}..."

    if pings is not None:
        payload["pings"] = [serialize_heartbeat_ping(ping) for ping in pings]

    return payload


def serialize_heartbeat_ping(item):
    return {
        "id": item.id,
        "heartbeat_id": item.heartbeat_id,
        "received_at": isoformat(item.received_at),
        "event_type": item.event_type,
        "status_before": item.status_before,
        "status_after": item.status_after,
        "message": item.message,
        "payload": item.payload or {},
        "remote_addr": item.remote_addr,
        "user_agent": item.user_agent,
        "alert_group_id": item.alert_group_id,
    }
