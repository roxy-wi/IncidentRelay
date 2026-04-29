from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from app.api.schemas.channels import ChannelCreateSchema, ChannelUpdateSchema
from app.modules.db import channels_repo, teams_repo
from app.notifiers.registry import get_notifier
from app.services.audit import write_audit
from app.services.rbac import get_allowed_team_ids, require_team_read, require_team_write
from app.services.serializers import serialize_channel
from app.services.validation import validate_body


channels_bp = Blueprint("channels_api", __name__)


CHANNEL_TYPES = ["telegram", "slack", "mattermost", "webhook", "discord", "teams", "email"]


@channels_bp.route("/types", methods=["GET"])
def list_channel_types():
    """
    Return supported channel types.
    """

    return jsonify(CHANNEL_TYPES)


@channels_bp.route("", methods=["GET"])
def list_channels():
    """
    Return channels.
    """

    team_id = request.args.get("team_id", type=int)

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error
        channels = channels_repo.list_channels(team_id=team_id)
    else:
        channels = channels_repo.list_channels(team_ids=get_allowed_team_ids())

    return jsonify([serialize_channel(channel) for channel in channels])


@channels_bp.route("/<int:channel_id>", methods=["GET"])
def get_channel(channel_id):
    """
    Return a single channel.
    """

    channel = channels_repo.get_channel(channel_id)

    if channel.team_id:
        error = require_team_read(channel.team_id)
        if error:
            return error

    return jsonify(serialize_channel(channel))


@channels_bp.route("", methods=["POST"])
def create_channel():
    """
    Create a notification channel.
    """

    payload, error = validate_body(ChannelCreateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    channel = channels_repo.create_channel(
        team_id=payload.team_id,
        name=payload.name,
        channel_type=payload.channel_type,
        config=payload.config,
        enabled=payload.enabled,
        group_id=teams_repo.get_team(payload.team_id).group_id,
    )

    write_audit(
        "channel.create",
        object_type="channel",
        object_id=channel.id,
        team_id=channel.team.id if channel.team else None,
        data=payload.model_dump(),
    )

    return jsonify(serialize_channel(channel)), 201


@channels_bp.route("/<int:channel_id>", methods=["PUT"])
def update_channel(channel_id):
    """
    Update a notification channel.
    """

    payload, error = validate_body(ChannelUpdateSchema)
    if error:
        return error

    current_channel = channels_repo.get_channel(channel_id)

    if current_channel.team_id:
        error = require_team_write(current_channel.team_id)
        if error:
            return error

    if payload.team_id and payload.team_id != current_channel.team_id:
        error = require_team_write(payload.team_id)
        if error:
            return error

    channel = channels_repo.update_channel(
        channel_id,
        {
            "team": payload.team_id,
            "name": payload.name,
            "channel_type": payload.channel_type,
            "config": payload.config,
            "enabled": payload.enabled,
        },
    )

    write_audit(
        "channel.update",
        object_type="channel",
        object_id=channel.id,
        team_id=channel.team.id if channel.team else None,
        data=payload.model_dump(),
    )

    return jsonify(serialize_channel(channel))


@channels_bp.route("/<int:channel_id>", methods=["DELETE"])
def delete_channel(channel_id):
    """
    Disable a notification channel.
    """

    channel_before = channels_repo.get_channel(channel_id)

    if channel_before.team_id:
        error = require_team_write(channel_before.team_id)
        if error:
            return error

    channel = channels_repo.disable_channel(channel_id)

    write_audit(
        "channel.disable",
        object_type="channel",
        object_id=channel.id,
        team_id=channel.team.id if channel.team else None,
    )

    return jsonify(serialize_channel(channel))


@channels_bp.route("/<int:channel_id>/test", methods=["POST"])
def test_channel(channel_id):
    """
    Send a test notification through a channel.
    """

    channel = channels_repo.get_channel(channel_id)

    if channel.team_id:
        error = require_team_read(channel.team_id)
        if error:
            return error

    notifier = get_notifier(channel.channel_type)
    team = channel.team

    fake_alert = SimpleNamespace(
        id=0,
        team=team,
        route=None,
        assignee=None,
        status="test",
        source="manual-test",
        title="On-call test notification",
        message="This is a test notification from the IncidentRelay.",
        severity="info",
    )

    try:
        notifier.send(channel, fake_alert, "On-call test notification")
    except Exception as exc:
        write_audit(
            "channel.test.failed",
            object_type="channel",
            object_id=channel.id,
            team_id=team.id if team else None,
            message=str(exc),
        )
        return jsonify({"status": "failed", "error": str(exc)}), 400

    write_audit(
        "channel.test.sent",
        object_type="channel",
        object_id=channel.id,
        team_id=team.id if team else None,
    )

    return jsonify({"status": "sent"})
