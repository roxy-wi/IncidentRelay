"""Invalidate machine authority atomically with catalog ownership/state edits."""

from contextlib import contextmanager

from app.modules.db import changes_repo, incident_core_repo
from app.modules.common import utc_now
from app.modules.db.models import (
    ChangeGrant,
    ChangeGraphState,
    ChangeIntegration,
    ChangeSource,
    Group,
    Service,
    Team,
)
from app.services.change_intelligence.administration import (
    advance_revision,
    lock_catalog,
)
from app.services.change_intelligence.authorization import lock_row


def advance_graph_revision():
    """Publish catalog invalidation with the mutation, including new namespaces."""
    state = lock_catalog()
    revision = state.revision + 1
    ChangeGraphState.update(revision=revision, updated_at=utc_now()).where(
        ChangeGraphState.id == 1
    ).execute()
    changes_repo.request_job("discover_graph", 1, target_revision=revision)


@contextmanager
def graph_change():
    """Serialize dependency edits with publication without changing grants."""
    with incident_core_repo.write_transaction():
        lock_catalog()
        yield
        advance_graph_revision()


@contextmanager
def catalog_authorization_change(
    *, team_id=None, service_id=None, group_id=None, team_slug=None, group_slug=None
):
    """Lock affected principals before catalog/lifecycle writes, in ID order.

    The graph-state lock serializes grant creation with target changes. Service
    grants are found by both the pinned and current Team, so a move never carries
    old authority into the destination Team. Workers still recheck live state.
    """
    with incident_core_repo.write_transaction():
        lock_catalog()
        if team_slug is not None:
            team = Team.get_or_none(Team.slug == team_slug)
            team_id = team.id if team else None
        if group_slug is not None:
            group = Group.get_or_none(Group.slug == group_slug)
            group_id = group.id if group else None
        team_ids = {team_id} if team_id is not None else set()
        service = (
            Service.get_or_none(Service.id == service_id)
            if service_id is not None
            else None
        )
        if service:
            team_ids.add(service.team_id)
        team_scope = Team.id.in_(team_ids)
        if group_id is not None:
            team_scope |= Team.group == group_id
        teams = Team.select(Team.id).where(team_scope)
        service_scope = Service.team.in_(teams)
        if service_id is not None:
            service_scope |= Service.id == service_id
        services = Service.select(Service.id).where(service_scope)
        granted_sources = ChangeGrant.select(ChangeGrant.source).where(
            ChangeGrant.target_team.in_(teams)
            | ChangeGrant.target_service.in_(services)
        )
        source_principals = ChangeSource.select(ChangeSource.integration).where(
            ChangeSource.owner_team.in_(teams) | ChangeSource.id.in_(granted_sources)
        )
        principal_scope = ChangeIntegration.id.in_(source_principals)
        if group_id is not None:
            principal_scope |= ChangeIntegration.owner_group == group_id
        ids = [
            row.id
            for row in ChangeIntegration.select(ChangeIntegration.id)
            .where(principal_scope)
            .order_by(ChangeIntegration.id)
        ]
        integrations = [
            lock_row(ChangeIntegration.select().where(ChangeIntegration.id == value))
            for value in ids
        ]
        yield
        advance_graph_revision()
        for integration in integrations:
            # Nested Team/Service deletion may have already advanced this row.
            integration = ChangeIntegration.get_by_id(integration.id)
            advance_revision(integration)
