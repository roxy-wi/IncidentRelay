"""SQL visibility and explicit full/safe projections for human Change readers."""

from contextlib import contextmanager

from peewee import PostgresqlDatabase, fn

from app.db import database_proxy as db
from app.api.schemas.changes import InvalidChangeQuery
from app.modules.db.models import (
    Change,
    ChangeGraphState,
    ChangeIntegration,
    ChangeJob,
    ChangeService,
    ChangeServiceReference,
    ChangeSource,
    Group,
    Service,
    Team,
)
from app.services.change_intelligence.resolver import ENGINE_VERSION
from app.services.rbac import current_api_token, get_allowed_team_ids
from app.services.serializers.common import serialize_utc_datetime as timestamp


@contextmanager
def read_snapshot():
    """Keep authorization, counts and serialization in the same DB snapshot."""
    with db.atomic():
        if isinstance(db.obj, PostgresqlDatabase):
            db.execute_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def reader_teams():
    """Active Group is a UI preference; token Group/Team scopes remain boundaries."""
    teams = get_allowed_team_ids(use_active_group=False)
    token = current_api_token()
    if token and token.team_id:
        teams = [team_id for team_id in teams if team_id == token.team_id]
    return teams


def readable_services(team_ids):
    """Include disabled Services for owner history, but never deleted resources."""
    return Service.select().where(Service.team.in_(team_ids), Service.deleted == False)


def current_links(team_ids):
    """Trust only a complete mapping pass under the current graph and authority.

    A completed pass stamps every canonical link. New requests, partial batches,
    disabled principals and changed inputs fail closed before counts/pagination.
    """
    active_groups = Group.select(Group.id).where(
        Group.active == True, Group.deleted == False
    )
    active_teams = Team.select(Team.id).where(
        Team.active == True, Team.deleted == False, Team.group.in_(active_groups)
    )
    return (
        ChangeService.select(ChangeService)
        .join(Change)
        .join(ChangeIntegration)
        .join_from(Change, ChangeSource)
        .join_from(ChangeService, Service)
        .join_from(
            Change,
            ChangeJob,
            on=(
                (ChangeJob.entity_id == Change.id)
                & (ChangeJob.job_type == "resolve_references")
            ),
        )
        .join_from(ChangeJob, ChangeGraphState, on=(ChangeGraphState.id == 1))
        .where(
            Service.team.in_(team_ids),
            Service.deleted == False,
            Service.enabled == True,
            ChangeService.verification_state == "trusted",
            ChangeIntegration.active == True,
            ChangeSource.active == True,
            Change.owner_team.in_(active_teams),
            ChangeIntegration.owner_group.is_null(True)
            | ChangeIntegration.owner_group.in_(active_groups),
            ChangeJob.state.in_(("done", "pending")),
            ChangeJob.cursor.is_null(True),
            ChangeJob.last_error_class.is_null(True),
            ChangeJob.requested_generation == ChangeJob.claimed_generation,
            ChangeJob.target_revision == Change.revision,
            ChangeJob.auth_revision == ChangeIntegration.auth_revision,
            ChangeJob.graph_revision == ChangeGraphState.revision,
            ChangeJob.engine_version == ENGINE_VERSION,
        )
    )


def visible_changes(team_ids):
    """Do not retrieve a private Change and attempt to redact it after pagination."""
    return (
        Change.select(Change, ChangeSource, ChangeIntegration, Team)
        .join(ChangeSource)
        .join_from(Change, ChangeIntegration)
        .join_from(Change, Team)
        .where(
            Change.owner_team.in_(team_ids)
            | Change.id.in_(current_links(team_ids).select(ChangeService.change))
        )
    )


def resolve_service_filter(filters, team_ids):
    """Missing and inaccessible identities have the same response."""
    query = readable_services(team_ids)
    if filters.service_id is not None:
        return query.where(Service.id == filters.service_id).get().id
    if filters.service_slug is None:
        return None
    namespace = Team.select(Team.id).where(Team.id.in_(team_ids))
    namespace = namespace.where(
        Team.id == filters.team_id
        if filters.team_id is not None
        else Team.slug == filters.team_slug
    )
    return (
        query.where(Service.team.in_(namespace), Service.slug == filters.service_slug)
        .get()
        .id
    )


def filter_changes(filters, team_ids, *, service_id=None):
    """Private search/filter predicates are restricted to full owner projections."""
    query = visible_changes(team_ids)
    owned = Change.owner_team.in_(team_ids)
    if filters.scope_team_id is not None:
        if filters.scope_team_id not in team_ids:
            raise Change.DoesNotExist()
        team_services = readable_services([filters.scope_team_id]).select(Service.id)
        owned_links = ChangeService.select(ChangeService.change).where(
            ChangeService.service.in_(team_services)
        )
        safe_links = current_links([filters.scope_team_id]).select(ChangeService.change)
        query = query.where(
            (Change.owner_team == filters.scope_team_id)
            | (owned & Change.id.in_(owned_links))
            | Change.id.in_(safe_links)
        )
    if filters.owner_team_id is not None:
        if filters.owner_team_id not in team_ids:
            raise Change.DoesNotExist()
        query = query.where(Change.owner_team == filters.owner_team_id)
    selected_service = resolve_service_filter(filters, team_ids)
    if service_id is not None:
        readable_services(team_ids).where(Service.id == service_id).get()
        if selected_service is not None and selected_service != service_id:
            raise InvalidChangeQuery("Conflicting Service filters")
        selected_service = service_id
    if selected_service is not None:
        owned_links = ChangeService.select(ChangeService.change).where(
            ChangeService.service == selected_service
        )
        safe_links = (
            current_links(team_ids)
            .where(Service.id == selected_service)
            .select(ChangeService.change)
        )
        query = query.where(
            (owned & Change.id.in_(owned_links)) | Change.id.in_(safe_links)
        )
    if filters.search:
        term = filters.search.lower()
        private_match = Change.title.contains(
            term
        ) | Change.external_change_id.contains(term)
        public_match = Change.kind.contains(term)
        if term in "related change":
            public_match |= ~owned
        query = query.where((owned & private_match) | (~owned & public_match))
    for name in ("status", "environment"):
        value = getattr(filters, name)
        if value is not None:
            query = query.where(owned, getattr(Change, name) == value)
    if filters.source is not None:
        sources = ChangeSource.select(ChangeSource.id).where(
            ChangeSource.source == filters.source
        )
        query = query.where(owned, Change.source.in_(sources))
    if filters.kind is not None:
        query = query.where(Change.kind == filters.kind)
    if filters.occurred_from:
        query = query.where(Change.last_occurred_at >= filters.occurred_from)
    if filters.occurred_to:
        query = query.where(Change.last_occurred_at <= filters.occurred_to)
    return query.order_by(Change.last_occurred_at.desc(), Change.id.desc())


def page_result(query, filters, serialize):
    """Count and paginate only an already authorized SQL query."""
    total = query.count()
    return {
        "items": [
            serialize(row) for row in query.paginate(filters.page, filters.page_size)
        ],
        "pagination": {
            "page": filters.page,
            "page_size": filters.page_size,
            "total": total,
            "pages": (total + filters.page_size - 1) // filters.page_size,
        },
    }


def service_data(service):
    """Call only for a Service selected inside the reader's Team scope."""
    return {
        "id": service.id,
        "name": service.name,
        "slug": service.slug,
        "team_id": service.team_id,
    }


def service_links(change, team_ids, *, full):
    """An owner can inspect accessible history; a foreign reader needs live trust."""
    if full:
        return (
            ChangeService.select(ChangeService, Service)
            .join(Service)
            .where(
                ChangeService.change == change.id,
                Service.id.in_(readable_services(team_ids).select(Service.id)),
            )
            .order_by(ChangeService.id)
        )
    return (
        current_links(team_ids)
        .select(ChangeService, Service)
        .where(ChangeService.change == change.id)
        .order_by(ChangeService.id)
    )


def readable_references(team_ids):
    """Do not reveal references or diagnostic counts for inaccessible Services."""
    return (
        ChangeServiceReference.select()
        .where(
            ChangeServiceReference.namespace_team.in_(team_ids),
            ChangeServiceReference.resolved_service.is_null(True)
            | ChangeServiceReference.resolved_service.in_(
                readable_services(team_ids).select(Service.id)
            ),
        )
        .order_by(ChangeServiceReference.id)
    )


def reference_query(change, team_ids):
    """Select owner diagnostics for one Change inside the resource boundary."""
    return readable_references(team_ids).where(
        ChangeServiceReference.change == change.id
    )


def owner_context(changes, team_ids):
    """Load job state and scoped reference counts once for the displayed page."""
    ids = [change.id for change in changes if change.owner_team_id in team_ids]
    jobs = (
        {
            job.entity_id: job
            for job in ChangeJob.select().where(
                ChangeJob.job_type == "resolve_references", ChangeJob.entity_id.in_(ids)
            )
        }
        if ids
        else {}
    )
    counts = {}
    if ids:
        rows = (
            readable_references(team_ids)
            .where(ChangeServiceReference.change.in_(ids))
            .select(
                ChangeServiceReference.change,
                ChangeServiceReference.resolution_status,
                fn.COUNT(ChangeServiceReference.id),
            )
            .order_by()
            .group_by(
                ChangeServiceReference.change, ChangeServiceReference.resolution_status
            )
            .tuples()
        )
        for change_id, state, count in rows:
            counts.setdefault(change_id, {})[state] = count
    return {
        "jobs": jobs,
        "counts": counts,
        "graph_revision": ChangeGraphState.get_by_id(1).revision,
    }


def changes_page(query, filters, team_ids):
    """Load shared owner metadata once for all rows on the displayed page."""
    total = query.count()
    changes = list(query.paginate(filters.page, filters.page_size))
    context = owner_context(changes, team_ids)
    return {
        "items": [change_data(change, team_ids, context=context) for change in changes],
        "pagination": {
            "page": filters.page,
            "page_size": filters.page_size,
            "total": total,
            "pages": (total + filters.page_size - 1) // filters.page_size,
        },
    }


def reference_data(ref):
    """Owner diagnostics omit raw evidence and any credential identifiers."""
    return {
        "id": ref.id,
        "relation_type": ref.relation_type,
        "team_id": ref.namespace_team_id,
        "service_id": ref.resolved_service_id,
        "requested_service_id": ref.requested_service_id,
        "requested_service_slug": ref.requested_service_slug,
        "resolution_status": ref.resolution_status,
        "verification_state": ref.verification_state,
        "expires_at": timestamp(ref.expires_at),
        "last_error_code": ref.last_error_code,
    }


def change_data(change, team_ids, *, detail=False, context=None):
    """Construct separate whitelists; safe readers never receive owner fields."""
    full = change.owner_team_id in team_ids
    public = {
        "uid": str(change.uid),
        "projection": "full" if full else "safe",
        "title": change.title if full else "Related change",
        "kind": change.kind,
        "occurred_at": timestamp(change.last_occurred_at),
    }
    if not full:
        public["services"] = [
            {"service": service_data(link.service), "relation_type": link.relation_type}
            for link in service_links(change, team_ids, full=False).limit(5)
        ]
        return public
    context = context or owner_context([change], team_ids)
    job = context["jobs"].get(change.id)
    counts = context["counts"].get(change.id, {})
    total = sum(counts.values())
    resolved = counts.get("resolved", 0)
    mapping = (
        "mapped"
        if total and total == resolved
        else (
            "partially_mapped"
            if resolved
            else (
                "unmapped"
                if not total or counts.get("pending_resolution")
                else "mapping_failed"
            )
        )
    )
    current = bool(
        job
        and job.state in {"done", "pending"}
        and job.cursor is None
        and job.requested_generation == job.claimed_generation
        and job.target_revision == change.revision
        and job.auth_revision == change.integration.auth_revision
        and job.graph_revision == context["graph_revision"]
        and job.engine_version == ENGINE_VERSION
        and job.last_error_class is None
    )
    public.update(
        {
            "change_id": change.external_change_id,
            "source": change.source.source,
            "owner_team": {"id": change.owner_team_id, "name": change.owner_team.name},
            "environment": change.environment,
            "status": change.status,
            "lifecycle_conflict": change.lifecycle_conflict,
            "mapping_status": mapping,
            "reference_counts": counts,
            "revision": change.revision,
            "processing": {
                "state": job.state if job else "missing",
                "current": current,
                "error": job.last_error_class if job else None,
            },
            "started_at": timestamp(change.started_at),
            "completed_at": timestamp(change.completed_at),
        }
    )
    if detail:
        public.update(
            {
                "description": change.description,
                "external_url": change.external_url,
                "ordering_mode": change.ordering_mode,
                "diagnostics": change.diagnostics,
            }
        )
    return public


def event_data(event):
    """Event history is owner-only; raw snapshots and submitted identities stay private."""
    return {
        "uid": str(event.uid),
        "event_id": event.external_event_id,
        "event_type": event.event_type,
        "occurred_at": timestamp(event.occurred_at),
        "received_at": timestamp(event.received_at),
        "source_sequence": event.source_sequence,
        "actor": {"type": event.actor_type, "name": event.actor_label},
        "details": event.details,
        "fields": event.projection_fields,
    }
