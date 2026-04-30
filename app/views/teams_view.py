from flask import Blueprint, jsonify, request

from app.api.schemas.teams import TeamCreateSchema, TeamUpdateSchema, TeamUserAddSchema, TeamUserUpdateSchema
from app.modules.db import groups_repo, teams_repo
from app.services.audit import write_audit
from app.services.rbac import get_allowed_group_ids, require_group_write, require_team_read, require_team_write
from app.services.serializers import serialize_team
from app.services.validation import validate_body


teams_bp = Blueprint("teams_api", __name__)


@teams_bp.route("", methods=["GET"])
def list_teams():
    """
    Return teams visible to the current user.
    """

    user = request.current_user

    if user and user.is_admin:
        teams = teams_repo.list_teams(active_only=True)
    else:
        teams = teams_repo.list_teams(active_only=True, group_ids=get_allowed_group_ids())

    return jsonify([serialize_team(team) for team in teams])


@teams_bp.route("/<int:team_id>", methods=["GET"])
def get_team(team_id):
    """
    Return a single team.
    """

    error = require_team_read(team_id)
    if error:
        return error

    return jsonify(serialize_team(teams_repo.get_team(team_id)))


@teams_bp.route("", methods=["POST"])
def create_team():
    """
    Create a team.
    """

    payload, error = validate_body(TeamCreateSchema)
    if error:
        return error

    error = require_group_write(payload.group_id)
    if error:
        return error

    team = teams_repo.create_team(
        group_id=payload.group_id,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        escalation_enabled=payload.escalation_enabled,
        escalation_after_reminders=payload.escalation_after_reminders,
    )

    write_audit("team.create", object_type="team", object_id=team.id, group_id=team.group_id, team_id=team.id, data=payload.model_dump())
    return jsonify(serialize_team(team)), 201


@teams_bp.route("/<int:team_id>", methods=["PUT"])
def update_team(team_id):
    """
    Update a team.
    """

    error = require_team_write(team_id)
    if error:
        return error

    payload, error = validate_body(TeamUpdateSchema)
    if error:
        return error

    if payload.group_id != teams_repo.get_team(team_id).group_id:
        group_error = require_group_write(payload.group_id)
        if group_error:
            return group_error

    team = teams_repo.update_team(team_id, {
        "group": payload.group_id,
        "slug": payload.slug,
        "name": payload.name,
        "description": payload.description,
        "escalation_enabled": payload.escalation_enabled,
        "escalation_after_reminders": payload.escalation_after_reminders,
        "active": payload.active,
    })

    write_audit("team.update", object_type="team", object_id=team.id, group_id=team.group_id, team_id=team.id, data=payload.model_dump())
    return jsonify(serialize_team(team))


@teams_bp.route("/<int:team_id>", methods=["DELETE"])
def delete_team(team_id):
    """
    Disable a team.
    """

    error = require_team_write(team_id)
    if error:
        return error

    team = teams_repo.disable_team(team_id)
    write_audit("team.disable", object_type="team", object_id=team.id, group_id=team.group_id, team_id=team.id)
    return jsonify(serialize_team(team))


@teams_bp.route("/<int:team_id>/users", methods=["GET"])
def list_team_users(team_id):
    """
    Return team users.
    """

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
    """
    Add a user to a team.
    """

    error = require_team_write(team_id)
    if error:
        return error

    payload, error = validate_body(TeamUserAddSchema)
    if error:
        return error

    membership = teams_repo.add_user_to_team(team_id, payload.user_id, payload.role)
    team = teams_repo.get_team(team_id)

    if team.group_id:
        groups_repo.add_user_to_group(payload.user_id, team.group_id, payload.role)

    write_audit("team.user.add", object_type="team", object_id=team_id, group_id=team.group_id, team_id=team_id, data=payload.model_dump())
    return jsonify({"id": membership.id}), 201


@teams_bp.route("/users/<int:membership_id>", methods=["PUT"])
def update_team_user(membership_id):
    """
    Update a team membership.
    """

    membership = teams_repo.get_team_membership(membership_id)
    error = require_team_write(membership.team.id)
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
    """
    Remove a user from a team and from all rotations of this team.
    """
    membership = teams_repo.get_team_membership(membership_id)

    error = require_team_write(membership.team.id)
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


@teams_bp.route("/users/<int:membership_id>/disable", methods=["POST"])
def disable_team_user(membership_id):
    """
    Disable a team membership without deleting it.
    """
    membership = teams_repo.get_team_membership(membership_id)

    error = require_team_write(membership.team.id)
    if error:
        return error

    membership = teams_repo.disable_team_membership(membership_id)

    write_audit(
        "team.user.disable",
        object_type="team",
        object_id=membership.team.id,
        group_id=membership.team.group_id,
        team_id=membership.team.id,
        data={
            "membership_id": membership.id,
            "user_id": membership.user.id,
        },
    )

    return jsonify({"disabled": True, "id": membership.id})
