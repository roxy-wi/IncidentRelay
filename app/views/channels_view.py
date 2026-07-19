from types import SimpleNamespace

from flask import Blueprint, jsonify, request
from peewee import IntegrityError

from app.services.db_errors import handle_integrity_error
from app.api.schemas.channels import ChannelCreateSchema, ChannelUpdateSchema
from app.modules.db import channels_repo, teams_repo
from app.notifiers.registry import get_notifier, list_notifier_types
from app.notifiers.email.email_templates import DEFAULT_EMAIL_HTML_TEMPLATE
from app.services.audit import write_audit
from app.services.rbac import (
    current_user,
    get_allowed_team_or_group_resource_ids,
    require_team_or_group_resource_access,
)
from app.services.channel_config import merge_channel_config_secrets
from app.services.serializers.channels import serialize_channel
from app.services.validation import make_error_response, validate_body
from app.services.service_catalog.reconciliation import reconcile_channel_services

channels_bp = Blueprint("channels_api", __name__)


def channel_name_conflict_response(name):
    """Return a consistent conflict response for duplicate channel names."""
    return jsonify({
        "error": "conflict",
        "message": "Channel with this name already exists in this team",
        "details": [
            {
                "field": "name",
                "loc": ["name"],
                "message": "Channel name must be unique within a team",
                "type": "unique",
                "input": name,
            }
        ],
    }), 409


def build_test_assignee(channel):
    """Return a fake assignee for channel tests that require profile contacts."""
    if channel.channel_type != "email":
        return None

    current_user = request.current_user
    return SimpleNamespace(
        id=getattr(current_user, "id", None),
        username=getattr(current_user, "username", "test-user"),
        display_name=getattr(current_user, "display_name", None),
        email=getattr(current_user, "email", None),
        phone=getattr(current_user, "phone", None),
    )


@channels_bp.route("/types", methods=["GET"])
def list_channel_types():
    """Return supported channel types."""
    return jsonify(list_notifier_types())


@channels_bp.route("/email-template/default", methods=["GET"])
def get_default_email_template():
    """Return the default HTML template used by email channels."""
    return jsonify({"html_template": DEFAULT_EMAIL_HTML_TEMPLATE})


@channels_bp.route("", methods=["GET"])
def list_channels():
    """Return channels."""
    team_id = request.args.get("team_id", type=int)

    if team_id:
        error = require_team_or_group_resource_access(team_id)
        if error:
            return error
        channels = channels_repo.list_channels(team_id=team_id)
    else:
        channels = channels_repo.list_channels(
            team_ids=get_allowed_team_or_group_resource_ids()
        )

    return jsonify([
        serialize_channel(channel, current_user=current_user())
        for channel in channels
    ])


@channels_bp.route("/<int:channel_id>", methods=["GET"])
def get_channel(channel_id):
    """Return a single channel."""
    channel = channels_repo.get_channel(channel_id)

    if channel.team_id:
        error = require_team_or_group_resource_access(channel.team_id)
        if error:
            return error

    return jsonify(serialize_channel(channel, current_user=current_user()))


@channels_bp.route("", methods=["POST"])
def create_channel():
    """Create a notification channel."""
    payload, error = validate_body(ChannelCreateSchema)
    if error:
        return error

    error = require_team_or_group_resource_access(
        payload.team_id,
        write_required=True,
    )
    if error:
        return error
    team = teams_repo.get_team(payload.team_id)

    existing_channel = channels_repo.get_channel_by_team_and_name(
        payload.team_id,
        payload.name,
    )

    if existing_channel:
        if not existing_channel.deleted:
            return channel_name_conflict_response(payload.name)

        channel = channels_repo.restore_channel(
            existing_channel.id,
            channel_type=payload.channel_type,
            config=payload.config,
            enabled=payload.enabled,
            group_id=team.group_id,
        )

        write_audit(
            "channel.restore",
            object_type="channel",
            object_id=channel.id,
            team_id=channel.team.id if channel.team else None,
            data=payload.model_dump(),
        )

        reconcile_channel_services(
            channel.id,
            trigger="channel_restored",
            actor_user=current_user(),
        )

        return jsonify(
            serialize_channel(
                channel,
                current_user=current_user(),
            )
        ), 201

    try:
        channel = channels_repo.create_channel(
            team_id=payload.team_id,
            name=payload.name,
            channel_type=payload.channel_type,
            config=payload.config,
            enabled=payload.enabled,
            group_id=team.group_id,
        )
    except IntegrityError as exc:
        existing_channel = channels_repo.get_channel_by_team_and_name(
            payload.team_id,
            payload.name,
        )

        if existing_channel:
            return channel_name_conflict_response(payload.name)

        return handle_integrity_error(exc)

    write_audit(
        "channel.create",
        object_type="channel",
        object_id=channel.id,
        team_id=channel.team.id if channel.team else None,
        data=payload.model_dump(),
    )

    reconcile_channel_services(
        channel.id,
        trigger="channel_restored",
        actor_user=current_user(),
    )

    return jsonify(serialize_channel(channel, current_user=current_user())), 201


@channels_bp.route("/<int:channel_id>", methods=["PUT"])
def update_channel(channel_id):
    """Update a notification channel."""
    payload, error = validate_body(ChannelUpdateSchema)
    if error:
        return error

    current_channel = channels_repo.get_channel(channel_id)

    if current_channel.team_id:
        error = require_team_or_group_resource_access(
            current_channel.team_id,
            write_required=True,
        )
        if error:
            return error

    if payload.team_id and payload.team_id != current_channel.team_id:
        error = require_team_or_group_resource_access(
            payload.team_id,
            write_required=True,
        )
        if error:
            return error

    target_team_id = payload.team_id or current_channel.team_id

    existing_channel = channels_repo.get_channel_by_team_and_name(
        target_team_id,
        payload.name,
        exclude_channel_id=channel_id,
    )

    if existing_channel:
        return channel_name_conflict_response(payload.name)

    try:
        merged_config = merge_channel_config_secrets(
            payload.channel_type,
            payload.config,
            current_channel.channel_type,
            current_channel.config,
        )
    except ValueError as exc:
        return jsonify({
            "error": "validation_error",
            "message": str(exc),
        }), 400

    update_data = {
        "team": payload.team_id,
        "name": payload.name,
        "channel_type": payload.channel_type,
        "config": merged_config,
        "enabled": payload.enabled,
    }

    if payload.team_id and payload.team_id != current_channel.team_id:
        update_data["group"] = teams_repo.get_team(payload.team_id).group_id

    try:
        channel = channels_repo.update_channel(
            channel_id,
            update_data,
        )
    except IntegrityError as exc:
        existing_channel = channels_repo.get_channel_by_team_and_name(
            target_team_id,
            payload.name,
            exclude_channel_id=channel_id,
        )

        if existing_channel:
            return channel_name_conflict_response(payload.name)

        return handle_integrity_error(exc)

    write_audit(
        "channel.update",
        object_type="channel",
        object_id=channel.id,
        team_id=channel.team.id if channel.team else None,
        data=payload.model_dump(),
    )

    reconcile_channel_services(
        channel.id,
        trigger="channel_updated",
        actor_user=current_user(),
    )

    return jsonify(serialize_channel(channel, current_user=current_user()))


@channels_bp.route("/<int:channel_id>/disable", methods=["POST"])
def disable_channel(channel_id):
    """Disable a notification channel without deleting it."""
    channel_before = channels_repo.get_channel(channel_id)

    if channel_before.team_id:
        error = require_team_or_group_resource_access(
            channel_before.team_id,
            write_required=True,
        )
        if error:
            return error

    channel = channels_repo.disable_channel(channel_id)

    write_audit(
        "channel.disable",
        object_type="channel",
        object_id=channel.id,
        team_id=channel.team.id if channel.team else None,
        data={"name": channel.name, "enabled": False},
    )

    reconcile_channel_services(
        channel.id,
        trigger="channel_enabled",
        actor_user=current_user(),
    )

    return jsonify(serialize_channel(channel, current_user=current_user()))


@channels_bp.route("/<int:channel_id>/enable", methods=["POST"])
def enable_channel(channel_id):
    """Enable a disabled notification channel."""
    channel_before = channels_repo.get_channel(channel_id)

    if channel_before.team_id:
        error = require_team_or_group_resource_access(
            channel_before.team_id,
            write_required=True,
        )
        if error:
            return error

    channel = channels_repo.enable_channel(channel_id)

    write_audit(
        "channel.enable",
        object_type="channel",
        object_id=channel.id,
        team_id=channel.team.id if channel.team else None,
        data={"name": channel.name, "enabled": True},
    )

    reconcile_channel_services(
        channel.id,
        trigger="channel_enabled",
        actor_user=current_user(),
    )

    return jsonify(serialize_channel(channel, current_user=current_user()))


@channels_bp.route("/<int:channel_id>", methods=["DELETE"])
def delete_channel(channel_id):
    """Delete a notification channel.

    The channel is soft-deleted so historical data remains preserved.
    """
    channel_before = channels_repo.get_channel(channel_id)

    if channel_before.team_id:
        error = require_team_or_group_resource_access(
            channel_before.team_id,
            write_required=True,
        )
        if error:
            return error

    channel = channels_repo.delete_channel(channel_id)

    write_audit(
        "channel.delete",
        object_type="channel",
        object_id=channel.id,
        team_id=channel.team.id if channel.team else None,
        data={
            "name": channel.name,
            "channel_type": channel.channel_type,
            "deleted": True,
        },
    )

    reconcile_channel_services(
        channel.id,
        trigger="channel_enabled",
        actor_user=current_user(),
    )

    return jsonify({"deleted": True, "id": channel.id, "name": channel.name})


@channels_bp.route("/<int:channel_id>/test", methods=["POST"])
def test_channel(channel_id):
    """Send a test notification through a channel."""
    channel = channels_repo.get_channel(channel_id)

    if channel.team_id:
        error = require_team_or_group_resource_access(channel.team_id)
        if error:
            return error

    notifier = get_notifier(channel.channel_type)
    team = channel.team
    fake_alert = SimpleNamespace(
        id=0,
        team=team,
        route=None,
        assignee=build_test_assignee(channel),
        status="test",
        source="manual-test",
        title="IncidentRelay test notification",
        message="This is a test notification from the IncidentRelay.",
        severity="info",
    )

    try:
        notifier.send(channel, fake_alert, "IncidentRelay test notification", event_type="test")
    except Exception as exc:
        write_audit(
            "channel.test.failed",
            object_type="channel",
            object_id=channel.id,
            team_id=team.id if team else None,
            message=str(exc),
        )
        return make_error_response(
            error="channel_test_failed",
            message="Channel test failed.",
            status_code=400,
            status="failed",
        )

    write_audit(
        "channel.test.sent",
        object_type="channel",
        object_id=channel.id,
        team_id=team.id if team else None,
    )

    return jsonify({"status": "sent"})
