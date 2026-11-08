"""Machine identity and scoped claims, independent of HTTP and worker lifetime."""

from contextlib import contextmanager

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import incident_core_repo
from app.modules.db.transactions import lock_row
from app.modules.db.models import (
    ApiToken,
    ChangeGrant,
    ChangeIntegration,
    ChangeSource,
    Group,
    Service,
    Team,
)
from app.services.integrations.auth import hash_token


class ChangeAccessDenied(PermissionError):
    """A uniform denial that does not disclose resource existence."""


def active_team(team_id):
    """Return an active Team in an active Group, or the same denial for all IDs."""
    team = (
        Team.select(Team)
        .join(Group)
        .where(
            Team.id == team_id,
            Team.active == True,
            Team.deleted == False,
            Group.active == True,
            Group.deleted == False,
        )
        .first()
    )
    if team is None:
        raise ChangeAccessDenied("Change access denied")
    return team


def active_integration_group(integration):
    """Central integrations have no Group; owned ones require a live owner."""
    return (
        integration.owner_group_id is None
        or Group.select()
        .where(
            Group.id == integration.owner_group_id,
            Group.active == True,
            Group.deleted == False,
        )
        .exists()
    )


def scoped_team(integration, team_id):
    """Keep delegated authority inside its Group even after a catalog move."""
    team = active_team(team_id)
    if not active_integration_group(integration) or (
        integration.owner_group_id is not None
        and team.group_id != integration.owner_group_id
    ):
        raise ChangeAccessDenied("Change access denied")
    return team


def valid_machine_token(token, integration):
    """Check a credential without inheriting any human authority."""
    return bool(
        token
        and integration
        and integration.active
        and active_integration_group(integration)
        and token.change_integration_id == integration.id
        and token.active
        and not token.deleted
        and (token.expires_at is None or token.expires_at > utc_now())
        and token.scopes == ["changes:ingest"]
        and token.user_id is None
        and token.group_id is None
        and token.team_id is None
    )


def find_machine_token(raw_token):
    """Find even revoked machine credentials so they cannot fall back to JWT."""
    if not raw_token:
        return None
    return ApiToken.get_or_none(
        ApiToken.token_hash == hash_token(raw_token),
        ApiToken.change_integration.is_null(False),
    )


@contextmanager
def authorized_source(integration_id, owner_team_id, source_name, *, raw_token=None):
    """Hold current authority through a caller's write transaction.

    New intake supplies a raw credential and rechecks it under the integration
    lock. Accepted work supplies only the stable integration identity. Neither
    path publishes anything here; stage 4/5 writers must write inside this block.
    """
    with incident_core_repo.write_transaction():
        integration = lock_row(
            ChangeIntegration.select().where(
                ChangeIntegration.id == integration_id,
            )
        )
        if (
            integration is None
            or not integration.active
            or not active_integration_group(integration)
        ):
            raise ChangeAccessDenied("Change access denied")
        if raw_token is not None:
            token = find_machine_token(raw_token)
            if not valid_machine_token(token, integration):
                raise ChangeAccessDenied("Change access denied")
            # Saving a stale whole token here could undo a concurrent revocation.
            ApiToken.update(last_used_at=utc_now()).where(
                ApiToken.id == token.id
            ).execute()
        scoped_team(integration, owner_team_id)
        source = ChangeSource.get_or_none(
            ChangeSource.integration == integration.id,
            ChangeSource.owner_team == owner_team_id,
            ChangeSource.source == source_name,
            ChangeSource.active == True,
        )
        if source is None:
            raise ChangeAccessDenied("Change access denied")
        yield source, integration.auth_revision


def authorize_reference(
    source, capability, *, team_id, service_id=None, service_slug=None
):
    """Resolve an authorized identity, returning None for a permitted pending slug.

    Must run inside authorized_source. Reference permission includes lookup only;
    it never grants a changed/reported_affected assertion. A Service grant cannot
    authorize a not-yet-existing slug, or follow a Service to another Team.
    """
    if not db.in_transaction():
        raise RuntimeError("Reference authorization requires a transaction")
    if capability not in {"reference", "changed", "reported_affected"}:
        raise ValueError("Unknown Change capability")
    if (service_id is None) == (service_slug is None):
        raise ValueError("Specify exactly one Service ID or slug")
    scoped_team(source.integration, team_id)
    capabilities = (
        ["reference", "changed", "reported_affected"]
        if capability == "reference"
        else [capability]
    )
    grants = ChangeGrant.select().where(
        ChangeGrant.source == source.id,
        ChangeGrant.active == True,
        ChangeGrant.target_team == team_id,
        ChangeGrant.capability.in_(capabilities),
    )
    team_grant = grants.where(ChangeGrant.target_service.is_null(True)).exists()
    # An unauthorized ID/slug is indistinguishable from an absent/deleted one.
    services = Service.select().where(
        Service.team == team_id,
        Service.enabled == True,
        Service.deleted == False,
    )
    if not team_grant:
        services = services.where(
            Service.id.in_(grants.select(ChangeGrant.target_service))
        )
    identity = (
        Service.id == service_id
        if service_id is not None
        else Service.slug == service_slug
    )
    service = services.where(identity).first()
    if service is not None:
        return service
    if team_grant and service_slug is not None:
        # A disabled/deleted row is invalid, not a pending new identity.
        if (
            not Service.select()
            .where(Service.team == team_id, Service.slug == service_slug)
            .exists()
        ):
            return None
    raise ChangeAccessDenied("Change access denied")
