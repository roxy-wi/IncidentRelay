"""Versioned Change links using the existing Incident transaction/CAS contract."""

from peewee import DoesNotExist

from app.modules.common import utc_now
from app.modules.db import incident_core_repo
from app.modules.db.models import Change, ChangeIncidentLink, Incident
from app.services.audit import write_audit
from app.services.change_intelligence import reading, reviewing
from app.services.rbac import current_user
from app.services.serializers.common import serialize_utc_datetime as timestamp


def incident_query(teams):
    return Incident.select().where(reviewing.visible_teams(Incident.team, teams))


def link_query(teams, *, incident_id=None, change_id=None, include_removed=False):
    """Both ends must be visible before counting or paginating links."""
    query = ChangeIncidentLink.select().where(
        ChangeIncidentLink.incident.in_(incident_query(teams).select(Incident.id)),
        ChangeIncidentLink.change.in_(reading.visible_changes(teams).select(Change.id)),
    )
    if incident_id is not None:
        query = query.where(ChangeIncidentLink.incident == incident_id)
    if change_id is not None:
        query = query.where(ChangeIncidentLink.change == change_id)
    if not include_removed:
        query = query.where(ChangeIncidentLink.removed_at.is_null(True))
    return query.order_by(ChangeIncidentLink.id.desc())


def link_data(link, teams):
    incident = link.incident
    return {
        "id": link.id,
        "change": reading.change_data(link.change, teams),
        "incident": {"id": incident.id, "title": incident.title},
        "relation_type": link.relation_type,
        "row_version": link.row_version,
        "linked_by": link.linked_by_id,
        "linked_at": timestamp(link.linked_at),
        "removed_by": link.removed_by_id,
        "removed_at": timestamp(link.removed_at),
        "can_manage": reviewing.can_respond(incident, teams),
    }


def lock_incident(incident_id, teams):
    incident_query(teams).where(Incident.id == incident_id).get()
    incident = incident_core_repo.lock_incident(incident_id)
    if incident is None:
        raise DoesNotExist()
    incident_query(teams).where(Incident.id == incident_id).get()
    reviewing.require_response(incident, teams)
    return incident


def record_change(incident, link, action, note, before):
    """Only identifiers/roles reach the shared timeline; private Change text stays out."""
    try:
        incident_core_repo.compare_and_swap(incident.id, incident.row_version)
    except incident_core_repo.IncidentConflictError as error:
        raise reviewing.ReviewConflict(
            "incident_changed", "The Incident changed; reload before changing its links"
        ) from error
    data = {
        "link_id": link.id,
        "change_uid": str(link.change.uid),
        "relation_type": link.relation_type,
        "row_version": link.row_version,
    }
    incident_core_repo.create_event(
        incident.id,
        action,
        user_id=current_user().id,
        data=data,
    )
    write_audit(
        "incident." + action,
        object_type="incident",
        object_id=incident.id,
        group_id=incident.team.group_id if incident.team_id else None,
        team_id=incident.team_id,
        message=note,
        data={**data, "before": before},
    )


def add_link(incident_id, payload):
    """Exact active duplicates are no-ops; restores require the removed version."""
    with reviewing.change_transaction(payload.change_uid) as (change, teams):
        incident = lock_incident(incident_id, teams)
        link = ChangeIncidentLink.get_or_none(
            ChangeIncidentLink.change == change.id,
            ChangeIncidentLink.incident == incident.id,
        )
        before = None
        if link:
            if link.removed_at is None:
                if link.relation_type != payload.relation_type:
                    raise reviewing.ReviewConflict(
                        "incident_role_conflict",
                        "This Change is already linked with another role",
                    )
                return link_data(link, teams), 200
            if payload.row_version is None:
                raise reviewing.ReviewConflict(
                    "incident_link_removed",
                    "Reload the removed link before restoring it",
                )
            if payload.row_version != link.row_version:
                raise reviewing.ReviewConflict(
                    "incident_link_changed",
                    "Reload the removed link before restoring it",
                )
            before = {
                "row_version": link.row_version,
                "removed_at": timestamp(link.removed_at),
            }
            link.relation_type = payload.relation_type
            link.linked_by = current_user().id
            link.linked_at = utc_now()
            link.removed_by = None
            link.removed_at = None
            link.row_version += 1
            link.save()
        else:
            if payload.row_version is not None:
                raise reviewing.ReviewConflict(
                    "incident_link_missing", "The link no longer exists"
                )
            link = ChangeIncidentLink.create(
                change=change,
                incident=incident,
                relation_type=payload.relation_type,
                linked_by=current_user().id,
            )
        record_change(incident, link, "change_linked", payload.note, before)
        return link_data(link, teams), 201


def update_link(incident_id, link_id, payload, *, remove=False):
    """Serialize with all Incident writes and reject stale link mutations."""
    # This lookup is not authorization; recheck both ends after acquiring locks.
    initial = ChangeIncidentLink.get(
        ChangeIncidentLink.id == link_id, ChangeIncidentLink.incident == incident_id
    )
    with reviewing.change_transaction(initial.change.uid) as (_change, teams):
        incident = lock_incident(incident_id, teams)
        link = (
            link_query(teams, incident_id=incident_id, include_removed=True)
            .where(ChangeIncidentLink.id == link_id)
            .get()
        )
        if link.removed_at is not None:
            raise reviewing.ReviewConflict(
                "incident_link_removed",
                "This link was removed; reload before restoring it",
            )
        if link.row_version != payload.row_version:
            raise reviewing.ReviewConflict(
                "incident_link_changed",
                "This link was modified; reload before changing it",
            )
        before = {"row_version": link.row_version, "relation_type": link.relation_type}
        if not remove and payload.relation_type == link.relation_type:
            return link_data(link, teams)
        values = (
            {"removed_at": utc_now(), "removed_by": current_user().id}
            if remove
            else {"relation_type": payload.relation_type}
        )
        changed = (
            ChangeIncidentLink.update(
                **values,
                row_version=ChangeIncidentLink.row_version + 1,
            )
            .where(
                ChangeIncidentLink.id == link.id,
                ChangeIncidentLink.row_version == payload.row_version,
            )
            .execute()
        )
        if changed != 1:
            raise reviewing.ReviewConflict(
                "incident_link_changed",
                "This link was modified; reload before changing it",
            )
        link = ChangeIncidentLink.get_by_id(link.id)
        record_change(
            incident,
            link,
            "change_unlinked" if remove else "change_relation_changed",
            payload.note,
            before,
        )
        return link_data(link, teams)
