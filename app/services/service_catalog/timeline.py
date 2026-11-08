from flask import has_request_context, request
from peewee import JOIN, IntegrityError, fn

from app.modules.db.models import (
    Change,
    ChangeEvent,
    ChangeImpact,
    ChangeService,
    Service,
    ServiceEvent,
)
from app.modules.common import utc_now
from app.modules.user_colors import user_color


def publish_service_event(
    service,
    *,
    category,
    event_type,
    title,
    summary=None,
    source="incidentrelay",
    source_ref=None,
    dedup_key=None,
    external_url=None,
    actor_user=None,
    actor_type=None,
    actor_label=None,
    severity=None,
    status=None,
    occurred_at=None,
    payload=None,
):
    if dedup_key:
        existing = ServiceEvent.get_or_none(
            ServiceEvent.service == service.id,
            ServiceEvent.source == source,
            ServiceEvent.dedup_key == dedup_key,
        )
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

        existing = ServiceEvent.get_or_none(
            ServiceEvent.service == service.id,
            ServiceEvent.source == source,
            ServiceEvent.dedup_key == dedup_key,
        )
        if existing:
            return existing

        raise


def _change_reader_teams():
    """Timeline access alone does not grant a personal token Change read scope."""
    from app.services.api_token_scopes import token_has_scopes
    from app.services.change_intelligence.reading import reader_teams
    from app.services.rbac import current_api_token

    if not has_request_context() or not getattr(request, "current_user", None):
        return []
    token = current_api_token()
    if token and not token_has_scopes(token.scopes, ["changes:read"]):
        return []
    return reader_teams()


def _visible_change_events(query, team_ids):
    """Apply current Service and Change visibility in SQL, before cursor/limit."""
    from app.services.change_intelligence.reading import (
        current_impacts,
        current_links,
        readable_services,
    )

    direct = (
        current_links(team_ids)
        .where(
            ChangeService.change == ChangeEvent.change,
            ChangeService.service == ServiceEvent.service,
            ChangeService.relation_type == ServiceEvent.change_relation_type,
        )
        .select(ChangeService.id)
    )
    inferred = (
        current_impacts(team_ids)
        .where(
            ChangeImpact.change == ChangeEvent.change,
            ChangeImpact.service == ServiceEvent.service,
            ServiceEvent.change_relation_type == "inferred_impact",
        )
        .select(ChangeImpact.id)
    )
    legacy = ServiceEvent.change_event.is_null(True) & (
        ServiceEvent.source != "change_intelligence"
    )
    allowed = ServiceEvent.service.in_(readable_services(team_ids).select(Service.id))
    allowed &= Change.owner_team.in_(team_ids) | fn.EXISTS(direct) | fn.EXISTS(inferred)
    return (
        query.join(ChangeEvent, JOIN.LEFT_OUTER)
        .join_from(ChangeEvent, Change, JOIN.LEFT_OUTER)
        .where(legacy | (ServiceEvent.change_event.is_null(False) & allowed))
    )


def list_service_events(
    service_id,
    *,
    category=None,
    event_type=None,
    limit=50,
    before=None,
    before_id=None,
    team_ids=None,
):
    query = ServiceEvent.select().where(ServiceEvent.service == service_id)
    query = _visible_change_events(
        query, _change_reader_teams() if team_ids is None else team_ids
    )

    if category:
        query = query.where(ServiceEvent.category == category)

    if event_type:
        query = query.where(ServiceEvent.event_type == event_type)

    if before is not None and before_id is not None:
        query = query.where(
            (ServiceEvent.occurred_at < before)
            | ((ServiceEvent.occurred_at == before) & (ServiceEvent.id < before_id))
        )
    elif before is not None:
        query = query.where(ServiceEvent.occurred_at < before)

    return list(
        query.order_by(ServiceEvent.occurred_at.desc(), ServiceEvent.id.desc()).limit(
            limit
        )
    )


def _serialize_actor(event):
    if event.actor_user_id and event.actor_user:
        user = event.actor_user
        return {
            "type": "user",
            "user_id": user.id,
            "color": user_color(user),
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
    if event.change_event_id:
        # Only the persisted whitelist is used; provider fields are never loaded.
        return {
            "id": event.id,
            "uid": str(event.uid),
            "service_id": event.service_id,
            "group_id": None,
            "team_id": None,
            "category": "change",
            "event_type": "change.recorded",
            "title": "Related change",
            "summary": None,
            "source": "change_intelligence",
            "source_ref": None,
            "dedup_key": None,
            "external_url": None,
            "actor": {
                "type": "system",
                "user_id": None,
                "display_name": "system",
                "email": None,
                "label": None,
            },
            "severity": None,
            "status": None,
            "occurred_at": _serialize_datetime(event.occurred_at),
            "recorded_at": _serialize_datetime(event.recorded_at),
            "schema_version": event.schema_version,
            "payload": {
                key: event.payload.get(key)
                for key in ("change_uid", "kind", "relation_type")
            },
        }
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
