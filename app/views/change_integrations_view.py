"""JWT administrator management; this blueprint exposes no Change intake."""

from contextlib import nullcontext

from flask import Blueprint, jsonify, request
from peewee import DoesNotExist, fn

from app.api.schemas import change_integrations as schemas
from app.middleware import load_jwt_user
from app.modules.db.models import (
    ApiToken,
    Change,
    ChangeGrant,
    ChangeIntegration,
    ChangeSource,
    Group,
    Service,
    Team,
)
from app.services.change_intelligence import administration as admin
from app.services.change_intelligence.authorization import ChangeAccessDenied
from app.services.change_intelligence.management import (
    can_manage_integrations,
    managed_groups,
    visible_integrations,
)
from app.services.serializers.common import serialize_utc_datetime
from app.services.serializers.tokens import serialize_api_token
from app.services.validation import make_error_response, validate_body

change_integrations_bp = Blueprint("change_integrations_api", __name__)


@change_integrations_bp.before_request
def require_admin_jwt():
    """Require a global/Group administrator JWT even if API auth is disabled."""
    if not load_jwt_user():
        return make_error_response("jwt_required", "Valid JWT token is required", 401)
    if not can_manage_integrations(request.current_user):
        return make_error_response("access_denied", "Administrator role required", 403)
    return None


@change_integrations_bp.after_request
def prevent_credential_caching(response):
    """Never cache credentials or administrative authorization state."""
    response.headers["Cache-Control"] = "no-store"
    return response


@change_integrations_bp.errorhandler(DoesNotExist)
def missing_resource(_error):
    return make_error_response("not_found", "Change configuration not found", 404)


@change_integrations_bp.errorhandler(ChangeAccessDenied)
def denied_resource(_error):
    return make_error_response("access_denied", "Change access denied", 403)


@change_integrations_bp.errorhandler(admin.ChangeConflict)
def conflicting_edit(error):
    return make_error_response("conflict", str(error), 409)


def integration_data(integration):
    """Serialize identity and the revision required by mutations."""
    return {
        "id": integration.id,
        "uid": str(integration.uid),
        "name": integration.name,
        "owner_group_id": integration.owner_group_id,
        "owner_group_name": (
            integration.owner_group.name if integration.owner_group_id else None
        ),
        "active": integration.active,
        "auth_revision": integration.auth_revision,
        "source_count": getattr(integration, "source_count", 0),
        "permission_count": getattr(integration, "permission_count", 0),
        "created_at": serialize_utc_datetime(integration.created_at),
        "updated_at": serialize_utc_datetime(integration.updated_at),
    }


def source_data(source, grants, teams, services, *, identity_editable):
    """Include display names without exposing catalog entries outside the scope."""
    owner = teams.get(source.owner_team_id)
    return {
        "id": source.id,
        "owner_team_id": source.owner_team_id,
        "owner_team_name": owner.name if owner else None,
        "owner_team_slug": owner.slug if owner else None,
        "source": source.source,
        "active": source.active,
        "ordering_mode": source.ordering_mode,
        "identity_editable": identity_editable,
        "grants": [grant_data(grant, teams, services) for grant in grants],
    }


def grant_data(grant, teams, services):
    """Keep unavailable pinned targets identifiable while hiding foreign names."""
    team = teams.get(grant.target_team_id)
    service = services.get(grant.target_service_id)
    if team is None or (service and service.team_id != grant.target_team_id):
        service = None
    return {
        "id": grant.id,
        "capability": grant.capability,
        "target_team_id": grant.target_team_id,
        "target_team_name": team.name if team else None,
        "target_team_slug": team.slug if team else None,
        "target_service_id": grant.target_service_id,
        "target_service_name": service.name if service else None,
        "target_service_slug": service.slug if service else None,
        "active": grant.active,
    }


def detail(integration_id):
    """Use a consistent read transaction for config and its edit revision."""
    with admin.admin_transaction(
        integration_id, actor_id=request.current_user.id
    ) as integration:
        result = integration_data(integration)
        sources = list(
            ChangeSource.select()
            .where(ChangeSource.integration == integration.id)
            .order_by(ChangeSource.id)
        )
        grants = list(
            ChangeGrant.select()
            .where(ChangeGrant.source.in_([source.id for source in sources]))
            .order_by(ChangeGrant.id)
        )
        team_ids = {source.owner_team_id for source in sources}
        team_ids.update(grant.target_team_id for grant in grants)
        team_query = Team.select().where(Team.id.in_(team_ids))
        if not request.current_user.is_admin:
            team_query = team_query.where(Team.group == integration.owner_group_id)
        teams = {team.id: team for team in team_query}
        # Include disabled/deleted targets so existing permissions remain readable.
        # Service moves must not disclose the destination's catalog information.
        services = {
            service.id: service
            for service in Service.select().where(
                Service.id.in_([grant.target_service_id for grant in grants]),
                Service.team.in_(list(teams)),
            )
        }
        grants_by_source = {}
        for grant in grants:
            grants_by_source.setdefault(grant.source_id, []).append(grant)
        used_sources = {
            change.source_id
            for change in Change.select(Change.source)
            .where(Change.source.in_([source.id for source in sources]))
            .distinct()
        }
        result["sources"] = [
            source_data(
                source,
                grants_by_source.get(source.id, []),
                teams,
                services,
                identity_editable=source.id not in used_sources,
            )
            for source in sources
        ]
        result["source_count"] = len(sources)
        result["permission_count"] = len(grants)
        result["tokens"] = [
            serialize_api_token(row)
            for row in ApiToken.select()
            .where(
                ApiToken.change_integration == integration.id,
            )
            .order_by(ApiToken.id.desc())
        ]
        return result


@change_integrations_bp.get("")
def list_integrations():
    cursor = max(0, request.args.get("after", 0, type=int))
    source_count = ChangeSource.select(fn.COUNT(ChangeSource.id)).where(
        ChangeSource.integration == ChangeIntegration.id
    )
    permission_count = (
        ChangeGrant.select(fn.COUNT(ChangeGrant.id))
        .join(ChangeSource)
        .where(ChangeSource.integration == ChangeIntegration.id)
    )
    rows = list(
        visible_integrations(request.current_user)
        .select(
            ChangeIntegration,
            source_count.alias("source_count"),
            permission_count.alias("permission_count"),
        )
        .where(ChangeIntegration.id > cursor)
        .order_by(ChangeIntegration.id)
        .limit(101)
    )
    return jsonify(
        {
            "items": [integration_data(row) for row in rows[:100]],
            "next_cursor": rows[99].id if len(rows) > 100 else None,
        }
    )


@change_integrations_bp.post("")
def create_integration():
    payload, error = validate_body(schemas.IntegrationCreate)
    if error:
        return error
    result = admin.create_integration(
        payload.name,
        actor_id=request.current_user.id,
        owner_group_id=payload.owner_group_id,
        owner_team_id=payload.owner_team_id,
    )
    return jsonify(detail(result.id)), 201


@change_integrations_bp.get("/targets")
def list_targets():
    """Return only permitted creation Groups and the integration's live targets."""
    user = request.current_user
    integration_id = request.args.get("integration_id", type=int)
    if "integration_id" in request.args and not integration_id:
        return make_error_response("invalid_id", "Invalid integration ID", 400)
    context = (
        admin.admin_transaction(integration_id, actor_id=user.id)
        if integration_id
        else nullcontext(None)
    )
    with context as integration:
        groups = managed_groups(user).order_by(Group.name, Group.id)
        teams = (
            Team.select()
            .where(
                Team.active == True,
                Team.deleted == False,
                Team.group.in_(groups.select(Group.id)),
            )
            .order_by(Team.name, Team.id)
        )
        if integration is not None and integration.owner_group_id is not None:
            teams = teams.where(Team.group == integration.owner_group_id)
        team_id = request.args.get("team_id", type=int)
        services = (
            Service.select()
            .where(
                Service.team == team_id,
                Service.enabled == True,
                Service.deleted == False,
                Service.team.in_(teams.select(Team.id)),
            )
            .order_by(Service.name, Service.id)
            if team_id
            else []
        )
        return jsonify(
            {
                "groups": [{"id": group.id, "name": group.name} for group in groups],
                "can_create_central": bool(user.is_admin),
                "teams": [
                    {
                        "id": team.id,
                        "name": team.name,
                        "slug": team.slug,
                        "group_id": team.group_id,
                    }
                    for team in teams
                ],
                "services": [
                    {"id": service.id, "name": service.name, "slug": service.slug}
                    for service in services
                ],
            }
        )


@change_integrations_bp.get("/<int:integration_id>")
def get_integration(integration_id):
    return jsonify(detail(integration_id))


@change_integrations_bp.patch("/<int:integration_id>")
def update_integration(integration_id):
    payload, error = validate_body(schemas.IntegrationUpdate)
    if error:
        return error
    admin.update_integration(integration_id, payload, actor_id=request.current_user.id)
    return jsonify(detail(integration_id))


@change_integrations_bp.post("/<int:integration_id>/sources")
def create_source(integration_id):
    payload, error = validate_body(schemas.SourceCreate)
    if error:
        return error
    admin.create_source(integration_id, payload, actor_id=request.current_user.id)
    return jsonify(detail(integration_id)), 201


@change_integrations_bp.patch("/<int:integration_id>/sources/<int:source_id>")
def update_source(integration_id, source_id):
    payload, error = validate_body(schemas.SourceUpdate)
    if error:
        return error
    admin.update_source(
        integration_id, source_id, payload, actor_id=request.current_user.id
    )
    return jsonify(detail(integration_id))


@change_integrations_bp.post("/<int:integration_id>/sources/<int:source_id>/grants")
def create_grant(integration_id, source_id):
    payload, error = validate_body(schemas.GrantCreate)
    if error:
        return error
    admin.create_grant(
        integration_id, source_id, payload, actor_id=request.current_user.id
    )
    return jsonify(detail(integration_id)), 201


@change_integrations_bp.patch(
    "/<int:integration_id>/sources/<int:source_id>/grants/<int:grant_id>"
)
def update_grant(integration_id, source_id, grant_id):
    payload, error = validate_body(schemas.GrantUpdate)
    if error:
        return error
    admin.update_grant(
        integration_id, source_id, grant_id, payload, actor_id=request.current_user.id
    )
    return jsonify(detail(integration_id))


@change_integrations_bp.post("/<int:integration_id>/tokens")
@change_integrations_bp.post("/<int:integration_id>/tokens/<int:token_id>/rotate")
def issue_token(integration_id, token_id=None):
    payload, error = validate_body(schemas.MachineTokenCreate)
    if error:
        return error
    token, raw = admin.issue_token(
        integration_id,
        payload,
        actor_id=request.current_user.id,
        rotate_token_id=token_id,
    )
    return jsonify({"token": raw, "credential": serialize_api_token(token)}), 201


@change_integrations_bp.post("/<int:integration_id>/tokens/<int:token_id>/revoke")
def revoke_token(integration_id, token_id):
    payload, error = validate_body(schemas.RevisionInput)
    if error:
        return error
    admin.revoke_token(
        integration_id, token_id, payload, actor_id=request.current_user.id
    )
    return jsonify(detail(integration_id))
