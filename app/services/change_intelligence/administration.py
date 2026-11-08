"""Admin mutations serialize permission edits and retain stable ownership."""

from contextlib import contextmanager
from datetime import timedelta
import re

from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo, tokens_repo
from app.modules.db.models import (
    ApiToken,
    Change,
    ChangeGrant,
    ChangeGraphState,
    ChangeIntegration,
    ChangeSource,
    Service,
)
from app.services.audit import record_audit
from app.services.change_intelligence.authorization import (
    active_integration_group,
    lock_row,
    scoped_team,
)
from app.services.integrations.auth import create_raw_token, hash_token
from app.services.change_intelligence.management import require_manager


class ChangeConflict(ValueError):
    """A namespace or expected authorization revision has changed."""


def lock_catalog():
    """Serialize namespace/grant creation with authorization-relevant catalog edits."""
    state = lock_row(ChangeGraphState.select().where(ChangeGraphState.id == 1))
    if state is None:
        raise RuntimeError("Change graph state is missing; run migrations")
    return state


def advance_revision(integration):
    """Invalidate derived authorization and persist work in the same transaction."""
    integration.auth_revision += 1
    integration.updated_at = utc_now()
    integration.save(
        only=[ChangeIntegration.auth_revision, ChangeIntegration.updated_at]
    )
    changes_repo.request_job(
        "discover_auth", integration.id, target_revision=integration.auth_revision
    )


@contextmanager
def admin_transaction(integration_id, expected_revision=None, *, actor_id=None):
    """Reject stale edits after locking graph state, then the machine principal."""
    with incident_core_repo.write_transaction():
        lock_catalog()
        integration = lock_row(
            ChangeIntegration.select().where(ChangeIntegration.id == integration_id)
        )
        if integration is None:
            raise ChangeIntegration.DoesNotExist()
        if actor_id is not None:
            try:
                require_manager(actor_id, integration.owner_group_id)
            except PermissionError as error:
                raise ChangeIntegration.DoesNotExist() from error
        if (
            expected_revision is not None
            and integration.auth_revision != expected_revision
        ):
            raise ChangeConflict("Integration changed; reload before editing")
        yield integration


def audit(actor_id, action, obj, integration_id, data=None):
    """Record mutation metadata only; no raw secrets or hashes enter the audit."""
    record_audit(
        "change_integration." + action,
        object_type=obj._meta.table_name,
        object_id=obj.id,
        group_id=ChangeIntegration.get_by_id(integration_id).owner_group_id,
        user_id=actor_id,
        data={"integration_id": integration_id, **(data or {})},
    )


def create_integration(name, *, actor_id, owner_group_id=None, owner_team_id=None):
    """Create the principal and its first source atomically, without implicit grants.

    Legacy internal callers may omit the Team to create an empty principal.
    The public creation API requires it and always creates one source.
    """
    with incident_core_repo.write_transaction():
        lock_catalog()
        require_manager(actor_id, owner_group_id, creating=True)
        integration = ChangeIntegration.create(name=name, owner_group=owner_group_id)
        audit(actor_id, "created", integration, integration.id)
        if owner_team_id is not None:
            scoped_team(integration, owner_team_id)
            base = (
                re.sub(r"[^\w-]+", "-", name.casefold()).strip("-")[:200] or "default"
            )
            source_name = base
            suffix = 0
            while (
                ChangeSource.select()
                .where(
                    ChangeSource.owner_team == owner_team_id,
                    ChangeSource.source == source_name,
                )
                .exists()
            ):
                suffix += 1
                source_name = f"{base}-{integration.id}-{suffix}"
            source = ChangeSource.create(
                integration=integration, owner_team=owner_team_id, source=source_name
            )
            audit(actor_id, "source_created", source, integration.id)
        return integration


def update_integration(integration_id, payload, *, actor_id):
    """Rename, disable or re-enable an integration without transferring history."""
    with admin_transaction(
        integration_id, payload.expected_revision, actor_id=actor_id
    ) as integration:
        values = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        for field, value in values.items():
            setattr(integration, field, value)
        integration.save(only=[getattr(ChangeIntegration, field) for field in values])
        advance_revision(integration)
        audit(actor_id, "updated", integration, integration.id, values)
        return integration


def create_source(integration_id, payload, *, actor_id):
    """Reserve a producer namespace permanently, including after deactivation."""
    with admin_transaction(
        integration_id, payload.expected_revision, actor_id=actor_id
    ) as integration:
        scoped_team(integration, payload.owner_team_id)
        if (
            ChangeSource.select()
            .where(
                ChangeSource.owner_team == payload.owner_team_id,
                ChangeSource.source == payload.source,
            )
            .exists()
        ):
            raise ChangeConflict("Source namespace is already reserved")
        source = ChangeSource.create(
            integration=integration,
            owner_team=payload.owner_team_id,
            source=payload.source,
            ordering_mode=payload.ordering_mode,
        )
        advance_revision(integration)
        audit(actor_id, "source_created", source, integration.id)
        return source


def update_source(integration_id, source_id, payload, *, actor_id):
    """Serialize identity edits with admitted writes; preserve existing history."""
    with admin_transaction(
        integration_id, payload.expected_revision, actor_id=actor_id
    ) as integration:
        source = ChangeSource.get(
            ChangeSource.id == source_id, ChangeSource.integration == integration.id
        )
        values = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        owner_team_id = values.get("owner_team_id", source.owner_team_id)
        source_name = values.get("source", source.source)
        identity_changed = (owner_team_id, source_name) != (
            source.owner_team_id,
            source.source,
        )
        if identity_changed:
            if Change.select().where(Change.source == source.id).exists():
                raise ChangeConflict(
                    "Source already has Changes; create a new source to change its name or Team"
                )
            if (
                ChangeSource.select()
                .where(
                    ChangeSource.owner_team == owner_team_id,
                    ChangeSource.source == source_name,
                    ChangeSource.id != source.id,
                )
                .exists()
            ):
                raise ChangeConflict("Source namespace is already reserved")
        if identity_changed or values.get("active", source.active):
            scoped_team(integration, owner_team_id)
        previous = {
            "source": source.source,
            "owner_team_id": source.owner_team_id,
            "active": source.active,
            "ordering_mode": source.ordering_mode,
        }
        source.source = source_name
        source.owner_team = owner_team_id
        source.active = values.get("active", source.active)
        source.ordering_mode = values.get("ordering_mode", source.ordering_mode)
        source.updated_at = utc_now()
        source.save()
        advance_revision(integration)
        audit(
            actor_id,
            "source_updated",
            source,
            integration.id,
            {"before": previous, "after": values},
        )
        return source


def validate_grant_target(integration, team_id, service_id):
    """Pin a grant to its existing Team and optional Service."""
    scoped_team(integration, team_id)
    if service_id is not None:
        service = Service.get_or_none(
            Service.id == service_id,
            Service.team == team_id,
            Service.deleted == False,
            Service.enabled == True,
        )
        if service is None:
            from app.services.change_intelligence.authorization import (
                ChangeAccessDenied,
            )

            raise ChangeAccessDenied("Change access denied")


def create_grant(integration_id, source_id, payload, *, actor_id):
    """Create a claim/lookup grant with a backend-independent target key."""
    with admin_transaction(
        integration_id, payload.expected_revision, actor_id=actor_id
    ) as integration:
        source = ChangeSource.get(
            ChangeSource.id == source_id, ChangeSource.integration == integration.id
        )
        validate_grant_target(
            integration, payload.target_team_id, payload.target_service_id
        )
        key = (
            f"service:{payload.target_service_id}"
            if payload.target_service_id is not None
            else f"team:{payload.target_team_id}"
        )
        if (
            ChangeGrant.select()
            .where(
                ChangeGrant.source == source.id,
                ChangeGrant.capability == payload.capability,
                ChangeGrant.target_key == key,
            )
            .exists()
        ):
            raise ChangeConflict("Grant already exists; update its active state")
        grant = ChangeGrant.create(
            source=source,
            capability=payload.capability,
            target_team=payload.target_team_id,
            target_service=payload.target_service_id,
            target_key=key,
        )
        advance_revision(integration)
        audit(actor_id, "grant_created", grant, integration.id)
        return grant


def update_grant(integration_id, source_id, grant_id, payload, *, actor_id):
    """Replace authority atomically and audit the previous explicit permission."""
    with admin_transaction(
        integration_id, payload.expected_revision, actor_id=actor_id
    ) as integration:
        source = ChangeSource.get(
            ChangeSource.id == source_id, ChangeSource.integration == integration.id
        )
        grant = ChangeGrant.get(
            ChangeGrant.id == grant_id, ChangeGrant.source == source.id
        )
        previous = {
            "source_id": grant.source_id,
            "capability": grant.capability,
            "target_team_id": grant.target_team_id,
            "target_service_id": grant.target_service_id,
            "active": grant.active,
        }
        values = {
            **previous,
            **payload.model_dump(exclude_unset=True, exclude={"expected_revision"}),
        }
        ChangeSource.get(
            ChangeSource.id == values["source_id"],
            ChangeSource.integration == integration.id,
        )
        identity_changed = any(
            values[key] != previous[key] for key in previous if key != "active"
        )
        if values["active"] or identity_changed:
            validate_grant_target(
                integration, values["target_team_id"], values["target_service_id"]
            )
        key = (
            f"service:{values['target_service_id']}"
            if values["target_service_id"] is not None
            else f"team:{values['target_team_id']}"
        )
        if (
            ChangeGrant.select()
            .where(
                ChangeGrant.source == values["source_id"],
                ChangeGrant.capability == values["capability"],
                ChangeGrant.target_key == key,
                ChangeGrant.id != grant.id,
            )
            .exists()
        ):
            raise ChangeConflict("Grant already exists; edit the existing permission")
        grant.source = values["source_id"]
        grant.capability = values["capability"]
        grant.target_team = values["target_team_id"]
        grant.target_service = values["target_service_id"]
        grant.target_key = key
        grant.active = values["active"]
        grant.updated_at = utc_now()
        grant.save()
        advance_revision(integration)
        audit(
            actor_id,
            "grant_updated",
            grant,
            integration.id,
            {"before": previous, "after": values},
        )
        return grant


def issue_token(integration_id, payload, *, actor_id, rotate_token_id=None):
    """Issue once; optionally revoke the old credential in the same transaction."""
    with admin_transaction(
        integration_id, payload.expected_revision, actor_id=actor_id
    ) as integration:
        if not integration.active or not active_integration_group(integration):
            raise ChangeConflict("Enable the integration before issuing credentials")
        if rotate_token_id is not None:
            old = ApiToken.get(
                ApiToken.id == rotate_token_id,
                ApiToken.change_integration == integration.id,
            )
            if not old.active or old.deleted:
                raise ChangeConflict("Credential was already revoked or rotated")
            tokens_repo.soft_delete_token(old.id)
        raw = create_raw_token()
        token = tokens_repo.create_api_token(
            payload.name,
            raw[:12],
            hash_token(raw),
            ["changes:ingest"],
            change_integration_id=integration.id,
            expires_at=utc_now() + timedelta(days=payload.days),
        )
        # Credential changes must not invalidate accepted work's auth revision.
        audit(
            actor_id,
            "token_rotated" if rotate_token_id else "token_created",
            token,
            integration.id,
            {"previous_token_id": rotate_token_id},
        )
        return token, raw


def revoke_token(integration_id, token_id, payload, *, actor_id):
    """Revoke new requests while preserving events and accepted work."""
    with admin_transaction(
        integration_id, payload.expected_revision, actor_id=actor_id
    ):
        token = ApiToken.get(
            ApiToken.id == token_id, ApiToken.change_integration == integration_id
        )
        if token.deleted:
            return token
        token = tokens_repo.soft_delete_token(token.id)
        audit(actor_id, "token_revoked", token, integration_id)
        return token
