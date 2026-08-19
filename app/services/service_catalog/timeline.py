
from peewee import IntegrityError

from app.modules.db.models import ServiceEvent
from app.modules.common import utc_now


def publish_service_event(service, *, category, event_type, title, summary=None, source="incidentrelay", source_ref=None, dedup_key=None, external_url=None, actor_user=None, actor_type=None, actor_label=None, severity=None, status=None, occurred_at=None, payload=None):
    if dedup_key:
        existing = ServiceEvent.get_or_none(ServiceEvent.service == service.id, ServiceEvent.source == source, ServiceEvent.dedup_key == dedup_key)
        if existing:
            return existing

    resolved_actor_type = actor_type or ("user" if actor_user else "system")

    try:
        return ServiceEvent.create(
            service=service.id,
            group=service.group_id,
            team=service.team_id,
            category=category,
            event_type=event_type,
            title=title,
            summary=summary,
            source=source,
            source_ref=source_ref,
            dedup_key=dedup_key,
            external_url=external_url,
            actor_type=resolved_actor_type,
            actor_user=actor_user.id if actor_user else None,
            actor_label=actor_label,
            severity=severity,
            status=status,
            occurred_at=occurred_at or utc_now(),
            payload=payload or {},
        )
    except IntegrityError:
        if not dedup_key:
            raise

        existing = ServiceEvent.get_or_none(ServiceEvent.service == service.id, ServiceEvent.source == source, ServiceEvent.dedup_key == dedup_key)
        if existing:
            return existing

        raise


def list_service_events(service_id, *, category=None, event_type=None, limit=50, before=None, before_id=None):
    query = ServiceEvent.select().where(ServiceEvent.service == service_id)

    if category:
        query = query.where(ServiceEvent.category == category)

    if event_type:
        query = query.where(ServiceEvent.event_type == event_type)

    if before is not None and before_id is not None:
        query = query.where((ServiceEvent.occurred_at < before) | ((ServiceEvent.occurred_at == before) & (ServiceEvent.id < before_id)))
    elif before is not None:
        query = query.where(ServiceEvent.occurred_at < before)

    return list(query.order_by(ServiceEvent.occurred_at.desc(), ServiceEvent.id.desc()).limit(limit))


def _serialize_actor(event):
    if event.actor_user_id and event.actor_user:
        user = event.actor_user
        return {
            "type": "user",
            "user_id": user.id,
            "display_name": user.display_name or user.username or user.email,
            "email": user.email,
            "label": event.actor_label,
        }

    if event.actor_label:
        return {
            "type": event.actor_type or "system",
            "user_id": None,
            "display_name": event.actor_label,
            "email": None,
            "label": event.actor_label,
        }

    return {
        "type": event.actor_type or "system",
        "user_id": None,
        "display_name": event.actor_type or "system",
        "email": None,
        "label": event.actor_label,
    }


def serialize_service_event(event):
    return {
        "id": event.id,
        "uid": str(event.uid),
        "service_id": event.service_id,
        "group_id": event.group_id,
        "team_id": event.team_id,
        "category": event.category,
        "event_type": event.event_type,
        "title": event.title,
        "summary": event.summary,
        "source": event.source,
        "source_ref": event.source_ref,
        "dedup_key": event.dedup_key,
        "external_url": event.external_url,
        "actor": _serialize_actor(event),
        "severity": event.severity,
        "status": event.status,
        "occurred_at": _serialize_datetime(event.occurred_at),
        "recorded_at": _serialize_datetime(event.recorded_at),
        "schema_version": event.schema_version,
        "payload": event.payload or {},
    }


def build_next_cursor(events, limit):
    if len(events) < limit:
        return None

    last_event = events[-1]

    return {
        "before": _serialize_datetime(last_event.occurred_at),
        "before_id": last_event.id,
    }


def _serialize_datetime(value):
    if value is None:
        return None

    return value.isoformat(timespec="seconds") + "Z"
