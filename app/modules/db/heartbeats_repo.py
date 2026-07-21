from datetime import datetime

from peewee import JOIN

from app.modules.db.models import Group, Heartbeat, HeartbeatInstance, HeartbeatPing, Service, Team
from app.services.integrations.auth import hash_token
from app.modules.common import utc_now


def list_heartbeats(
    *,
    team_id=None,
    team_ids=None,
    group_id=None,
    enabled_only=False,
    status=None,
    include_deleted=False,
):
    """Return heartbeat checks visible in a scope."""
    query = (
        Heartbeat
        .select(Heartbeat, Team, Group, Service)
        .join(Team, on=(Heartbeat.team == Team.id))
        .switch(Heartbeat)
        .join(Group, JOIN.LEFT_OUTER, on=(Heartbeat.group == Group.id))
        .switch(Heartbeat)
        .join(Service, JOIN.LEFT_OUTER, on=(Heartbeat.service == Service.id))
    )

    if not include_deleted:
        query = query.where(Heartbeat.deleted == False)

    if enabled_only:
        query = query.where(Heartbeat.enabled == True)

    if status:
        query = query.where(Heartbeat.status == status)

    if team_id:
        query = query.where(Heartbeat.team == team_id)
    elif team_ids is not None:
        team_ids = list(team_ids)
        if not team_ids:
            return []
        query = query.where(Heartbeat.team.in_(team_ids))

    if group_id:
        query = query.where(Heartbeat.group == group_id)

    return list(query.order_by(Team.slug.asc(), Heartbeat.name.asc()))


def list_heartbeats_for_service(service_id, *, enabled_only=False):
    query = Heartbeat.select().where(
        (Heartbeat.service == service_id)
        & (Heartbeat.deleted == False)
    )

    if enabled_only:
        query = query.where(Heartbeat.enabled == True)

    return list(query.order_by(Heartbeat.name.asc()))


def list_due_heartbeat_candidates(now, limit=100, team_ids=None):
    """Return enabled single-producer checks that may be overdue now."""
    query = (
        Heartbeat
        .select(Heartbeat, Team, Group, Service)
        .join(Team, on=(Heartbeat.team == Team.id))
        .switch(Heartbeat)
        .join(Group, JOIN.LEFT_OUTER, on=(Heartbeat.group == Group.id))
        .switch(Heartbeat)
        .join(Service, JOIN.LEFT_OUTER, on=(Heartbeat.service == Service.id))
        .where(
            (Heartbeat.deleted == False)
            & (Heartbeat.enabled == True)
            & (Heartbeat.status != "paused")
            & (Heartbeat.instance_tracking_enabled == False)
            & (
                (Heartbeat.next_expected_at.is_null(True))
                | (Heartbeat.next_expected_at <= now)
            )
        )
        .order_by(Heartbeat.next_expected_at.asc(nulls="FIRST"), Heartbeat.id.asc())
    )

    if team_ids is not None:
        team_ids = list(team_ids)
        if not team_ids:
            return []
        query = query.where(Heartbeat.team.in_(team_ids))

    return list(query.limit(limit))


def list_due_heartbeat_instance_candidates(now, limit=100, team_ids=None):
    """Return enabled heartbeat instances that may be overdue now."""
    query = (
        HeartbeatInstance
        .select(HeartbeatInstance, Heartbeat, Team, Group, Service)
        .join(Heartbeat, on=(HeartbeatInstance.heartbeat == Heartbeat.id))
        .join(Team, on=(Heartbeat.team == Team.id))
        .switch(Heartbeat)
        .join(Group, JOIN.LEFT_OUTER, on=(Heartbeat.group == Group.id))
        .switch(Heartbeat)
        .join(Service, JOIN.LEFT_OUTER, on=(Heartbeat.service == Service.id))
        .where(
            (Heartbeat.deleted == False)
            & (Heartbeat.enabled == True)
            & (Heartbeat.status != "paused")
            & (Heartbeat.instance_tracking_enabled == True)
            & (HeartbeatInstance.enabled == True)
            & (HeartbeatInstance.status != "paused")
            & (
                (HeartbeatInstance.next_expected_at.is_null(True))
                | (HeartbeatInstance.next_expected_at <= now)
            )
        )
        .order_by(HeartbeatInstance.next_expected_at.asc(nulls="FIRST"), HeartbeatInstance.id.asc())
    )

    if team_ids is not None:
        team_ids = list(team_ids)
        if not team_ids:
            return []
        query = query.where(Heartbeat.team.in_(team_ids))

    return list(query.limit(limit))


def get_heartbeat(heartbeat_id, *, include_deleted=False):
    query = Heartbeat.select().where(Heartbeat.id == heartbeat_id)

    if not include_deleted:
        query = query.where(Heartbeat.deleted == False)

    return query.get()


def get_heartbeat_or_none(heartbeat_id, *, include_deleted=False):
    if not heartbeat_id:
        return None

    query = Heartbeat.select().where(Heartbeat.id == heartbeat_id)

    if not include_deleted:
        query = query.where(Heartbeat.deleted == False)

    return query.first()


def get_heartbeat_by_slug(team_id, slug, *, include_deleted=False):
    query = Heartbeat.select().where(
        (Heartbeat.team == team_id)
        & (Heartbeat.slug == slug)
    )

    if not include_deleted:
        query = query.where(Heartbeat.deleted == False)

    return query.first()


def get_heartbeat_by_token(raw_token):
    if not raw_token:
        return None

    return (
        Heartbeat
        .select(Heartbeat, Team, Group, Service)
        .join(Team, on=(Heartbeat.team == Team.id))
        .switch(Heartbeat)
        .join(Group, JOIN.LEFT_OUTER, on=(Heartbeat.group == Group.id))
        .switch(Heartbeat)
        .join(Service, JOIN.LEFT_OUTER, on=(Heartbeat.service == Service.id))
        .where(
            (Heartbeat.token_hash == hash_token(raw_token))
            & (Heartbeat.deleted == False)
            & (Heartbeat.enabled == True)
            & (Team.deleted == False)
            & (Team.active == True)
        )
        .first()
    )


def create_heartbeat(data):
    return Heartbeat.create(**data)


def update_heartbeat(heartbeat, data):
    for key, value in data.items():
        setattr(heartbeat, key, value)

    heartbeat.updated_at = utc_now()
    heartbeat.save()
    return heartbeat


def soft_delete_heartbeat(heartbeat):
    now = utc_now()
    heartbeat.deleted = True
    heartbeat.deleted_at = now
    heartbeat.enabled = False
    heartbeat.updated_at = now
    heartbeat.save()
    return heartbeat


def record_ping(
    heartbeat,
    *,
    event_type="ping",
    instance_key=None,
    status_before=None,
    status_after=None,
    message=None,
    payload=None,
    remote_addr=None,
    user_agent=None,
    alert_group_id=None,
    received_at=None,
):
    return HeartbeatPing.create(
        heartbeat=heartbeat.id,
        event_type=event_type,
        instance_key=instance_key,
        status_before=status_before,
        status_after=status_after,
        message=message,
        payload=payload or {},
        remote_addr=remote_addr,
        user_agent=user_agent,
        alert_group=alert_group_id,
        received_at=received_at or utc_now(),
    )


def list_pings(heartbeat_id, limit=50):
    return list(
        HeartbeatPing
        .select()
        .where(HeartbeatPing.heartbeat == heartbeat_id)
        .order_by(HeartbeatPing.received_at.desc(), HeartbeatPing.id.desc())
        .limit(limit)
    )


def get_heartbeat_instance(heartbeat_id, instance_key):
    if not instance_key:
        return None
    return (
        HeartbeatInstance
        .select()
        .where(
            (HeartbeatInstance.heartbeat == heartbeat_id)
            & (HeartbeatInstance.instance_key == str(instance_key))
        )
        .first()
    )


def list_heartbeat_instances(heartbeat_id, *, enabled_only=False):
    query = HeartbeatInstance.select().where(HeartbeatInstance.heartbeat == heartbeat_id)
    if enabled_only:
        query = query.where(HeartbeatInstance.enabled == True)
    return list(query.order_by(HeartbeatInstance.instance_key.asc()))


def create_heartbeat_instance(heartbeat, instance_key, **data):
    return HeartbeatInstance.create(
        heartbeat=heartbeat.id if hasattr(heartbeat, "id") else heartbeat,
        instance_key=str(instance_key),
        **data,
    )


def update_heartbeat_instance(instance, data):
    for key, value in data.items():
        setattr(instance, key, value)
    instance.updated_at = utc_now()
    instance.save()
    return instance


def delete_heartbeat_instance(instance):
    instance.delete_instance()


def disable_heartbeat_instance(instance, status="paused"):
    instance.enabled = False
    instance.status = status
    instance.updated_at = utc_now()
    instance.save()
    return instance
