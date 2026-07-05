from flask import Blueprint, jsonify, request
from peewee import IntegrityError

from app.modules.db.common import integrity_conflict, unique_field_conflict
from app.api.schemas.roles import TEAM_MANAGER_ROLE
from app.api.schemas.teams import (
    TeamCreateSchema,
    TeamUpdateSchema,
    TeamUserAddSchema,
    TeamUserUpdateSchema,
)
from app.modules.db import groups_repo, teams_repo
from app.services.audit import write_audit
from app.services.rbac import (
    get_allowed_oncall_team_ids,
    require_group_write,
    require_team_user_admin,
    require_team_write,
    require_team_read,
)
from app.services.serializers.teams import serialize_team
from app.services.validation import validate_body

teams_bp = Blueprint("teams_api", __name__)


@teams_bp.route("", methods=["GET"])
def list_teams():
    """Return teams visible to the current user."""
    user = request.current_user
    include_inactive = request.args.get(
        "include_inactive",
        default=False,
        type=lambda value: str(value).lower() in {"1", "true", "yes", "on"},
    )
    active_only = not include_inactive

    if user and user.is_admin:
        teams = teams_repo.list_teams(active_only=active_only)
    else:
        team_ids = set(
            get_allowed_oncall_team_ids(
                use_active_group=True,
                active_only=active_only,
            )
        )
        teams = [
            team
            for team in teams_repo.list_teams(active_only=active_only)
            if team.id in team_ids
        ]
    return jsonify([serialize_team(team, current_user=user) for team in teams])


@teams_bp.route("/<int:team_id>", methods=["GET"])
def get_team(team_id):
    """Return a single team."""
    error = require_team_read(team_id)
    if error:
        return error
    return jsonify(serialize_team(
        teams_repo.get_team(team_id),
        current_user=request.current_user,
    ))


@teams_bp.route("", methods=["POST"])
def create_team():
    """Create a team."""
    payload, error = validate_body(TeamCreateSchema)
    if error:
        return error

    error = require_group_write(payload.group_id)
    if error:
        return error

    try:
        team = teams_repo.create_team(
            group_id=payload.group_id,
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            escalation_enabled=payload.escalation_enabled,
            escalation_after_reminders=payload.escalation_after_reminders,
            active=payload.active,
        )
    except IntegrityError as exc:
        error_text = str(exc).lower()

        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                payload.slug,
                "Team with this slug already exists",
            )

        return integrity_conflict("Team could not be saved because it conflicts with existing data")

    user = request.current_user
    if user and not user.is_admin:
        teams_repo.add_user_to_team(team.id, user.id, TEAM_MANAGER_ROLE)

    write_audit(
        "team.create",
        object_type="team",
        object_id=team.id,
        group_id=team.group_id,
        team_id=team.id,
        data=payload.model_dump(),
    )
    return jsonify(serialize_team(team, current_user=request.current_user)), 201


@teams_bp.route("/<int:team_id>", methods=["PUT"])
def update_team(team_id):
    """Update a team."""
    error = require_team_write(team_id)
    if error:
        return error

    payload, error = validate_body(TeamUpdateSchema)
    if error:
        return error

    current_team = teams_repo.get_team(team_id)
    if payload.group_id != current_team.group_id:
        if not request.current_user.is_admin:
            return jsonify({
                "error": "group_change_denied",
                "message": "Only global admin can move a team to another group",
            }), 403
        group_error = require_group_write(payload.group_id)
        if group_error:
            return group_error

    try:
        team = teams_repo.update_team(team_id, {
            "group": payload.group_id,
            "slug": payload.slug,
            "name": payload.name,
            "description": payload.description,
            "escalation_enabled": payload.escalation_enabled,
            "escalation_after_reminders": payload.escalation_after_reminders,
            "active": payload.active,
        })
    except IntegrityError as exc:
        error_text = str(exc).lower()

        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                payload.slug,
                "Team with this slug already exists",
            )

        return integrity_conflict("Team could not be saved because it conflicts with existing data")

    write_audit(
        "team.update",
        object_type="team",
        object_id=team.id,
        group_id=team.group_id,
        team_id=team.id,
        data=payload.model_dump(),
    )
    return jsonify(serialize_team(team, current_user=request.current_user))


@teams_bp.route("/<int:team_id>", methods=["DELETE"])
def delete_team(team_id):
    """Remove a team and all non-historical resources under it."""
    error = require_team_write(team_id)
    if error:
        return error

    team = teams_repo.remove_team(team_id)
    write_audit(
        "team.remove",
        object_type="team",
        object_id=team.id,
        group_id=team.group_id,
        team_id=team.id,
        data={
            "removed_rotations": True,
            "removed_routes": True,
            "removed_channels": True,
            "removed_silences": True,
            "historical_alerts_preserved": True,
        },
    )
    return jsonify({
        "deleted": True,
        "id": team.id,
    })


@teams_bp.route("/<int:team_id>/users", methods=["GET"])
def list_team_users(team_id):
    """Return team users."""
    error = require_team_read(team_id)
    if error:
        return error

    return jsonify([
        {
            "id": membership.id,
            "user_id": membership.user.id,
            "username": membership.user.username,
            "display_name": membership.user.display_name,
            "role": membership.role,
            "active": membership.active,
        }
        for membership in teams_repo.list_team_users(team_id)
    ])


@teams_bp.route("/<int:team_id>/users", methods=["POST"])
def add_team_user(team_id):
    """Add an existing group user to a team."""
    error = require_team_user_admin(team_id)
    if error:
        return error

    payload, error = validate_body(TeamUserAddSchema)
    if error:
        return error

    team = teams_repo.get_team(team_id)
    if team.group_id and not groups_repo.get_user_group_role(payload.user_id, team.group_id):
        return jsonify({
            "error": "user_not_in_group",
            "message": "User must already belong to the team's group before being added to the team",
        }), 400

    membership = teams_repo.add_user_to_team(
        team_id,
        payload.user_id,
        payload.role,
        active=payload.active,
    )
    write_audit(
        "team.user.add",
        object_type="team",
        object_id=team_id,
        group_id=team.group_id,
        team_id=team_id,
        data=payload.model_dump(),
    )
    return jsonify({
        "id": membership.id,
        "user_id": membership.user.id,
        "username": membership.user.username,
        "display_name": membership.user.display_name,
        "role": membership.role,
        "active": membership.active,
    }), 201


@teams_bp.route("/users/<int:membership_id>", methods=["PUT"])
def update_team_user(membership_id):
    """Update a team membership."""
    membership = teams_repo.get_team_membership(membership_id)
    error = require_team_user_admin(membership.team.id)
    if error:
        return error

    payload, error = validate_body(TeamUserUpdateSchema)
    if error:
        return error

    membership = teams_repo.update_team_membership(
        membership_id=membership_id,
        role=payload.role,
        active=payload.active,
    )
    write_audit(
        "team.user.update",
        object_type="team",
        object_id=membership.team.id,
        group_id=membership.team.group_id,
        team_id=membership.team.id,
        data={"membership_id": membership.id, **payload.model_dump()},
    )
    return jsonify({
        "id": membership.id,
        "user_id": membership.user.id,
        "username": membership.user.username,
        "display_name": membership.user.display_name,
        "role": membership.role,
        "active": membership.active,
    })


@teams_bp.route("/users/<int:membership_id>", methods=["DELETE"])
def delete_team_user(membership_id):
    """Remove a user from a team and from all rotations of this team."""
    membership = teams_repo.get_team_membership(membership_id)
    error = require_team_user_admin(membership.team.id)
    if error:
        return error

    data = teams_repo.delete_team_membership(membership_id)
    write_audit(
        "team.user.remove",
        object_type="team",
        object_id=data["team_id"],
        group_id=data["group_id"],
        team_id=data["team_id"],
        data={
            "membership_id": data["id"],
            "user_id": data["user_id"],
            "removed_from_team_rotations": True,
        },
    )
    return jsonify({"deleted": True, "id": membership_id})
