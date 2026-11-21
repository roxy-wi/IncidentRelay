"""Channel ownership must protect every API operation, including legacy rows."""

from unittest.mock import Mock

import pytest

from app.login import create_access_token
from app.modules.db import groups_repo, tokens_repo
from app.modules.db.models import AlertRouteChannel, AuditLog, NotificationChannel
from app.services.integrations.auth import hash_token
from app.settings import Config
from tests.factories import (
    add_user_to_team,
    attach_channel,
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
    unique,
)


OPERATIONS = ["get", "update", "disable", "enable", "delete", "test"]


def jwt_headers(user):
    """Authenticate requests through the real JWT middleware."""
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def bounded_token_headers(user, *, group=None, team=None):
    """Authenticate an administrator constrained by a persisted token."""
    raw = unique("channel-token")
    tokens_repo.create_token(
        name=raw,
        token_prefix=raw[:12],
        token_hash=hash_token(raw),
        scopes=["channels:read", "channels:write"],
        user=user.id,
        group=group.id if group else None,
        team=team.id if team else None,
    )
    return {"Authorization": f"Bearer {raw}"}


def update_payload(channel):
    """Return a valid update without an ownership field."""
    return {
        "name": channel.name + " updated",
        "channel_type": "webhook",
        "config": {"webhook_url": "https://example.com/updated"},
        "enabled": channel.enabled,
    }


def channel_request(client, channel, operation, headers):
    """Exercise the public endpoint for a channel operation."""
    path = f"/api/channels/{channel.id}"
    if operation == "update":
        return client.put(path, headers=headers, json=update_payload(channel))
    if operation == "get":
        return client.get(path, headers=headers)
    if operation == "delete":
        return client.delete(path, headers=headers)
    return client.post(f"{path}/{operation}", headers=headers)


@pytest.fixture
def notifier(monkeypatch):
    """Observe delivery attempts without sending external notifications."""
    notifier = Mock(spec=["send"])
    monkeypatch.setattr(
        "app.views.channels_view.get_notifier", Mock(return_value=notifier),
    )
    return notifier


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("principal", [
    "foreign_group", "group_viewer", "anonymous", "foreign_group_token",
    "same_group_team_token", "ownerless",
])
def test_channel_operations_deny_unauthorized_principals(
    client, db, monkeypatch, notifier, operation, principal,
):
    group = create_group()
    team = create_team(group)
    channel = create_channel(
        group, config={"webhook_url": "https://example.com/original"},
    )
    channel.enabled = operation != "enable"
    if principal == "ownerless":
        channel.group = None
    channel.save()
    link = attach_channel(create_route(team), channel)
    before = NotificationChannel.get_by_id(channel.id).__data__.copy()

    if principal == "anonymous":
        monkeypatch.setattr(Config, "API_AUTH_REQUIRED", False)
        headers = {}
    elif principal == "foreign_group":
        headers = jwt_headers(create_user(group=create_group()))
    elif principal == "group_viewer":
        headers = jwt_headers(create_user(group=group, group_role="viewer"))
    elif principal == "ownerless":
        headers = jwt_headers(create_user(is_admin=True))
    else:
        admin = create_user(is_admin=True)
        headers = bounded_token_headers(
            admin,
            group=create_group() if principal == "foreign_group_token" else group,
            team=team if principal == "same_group_team_token" else None,
        )
    audit_count = AuditLog.select().count()

    response = channel_request(client, channel, operation, headers)

    assert response.status_code == 403, response.get_json()
    assert NotificationChannel.get_by_id(channel.id).__data__ == before
    assert AlertRouteChannel.get_by_id(link.id).channel_id == channel.id
    assert AuditLog.select().count() == audit_count
    notifier.send.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("principal", [
    "group_editor", "group_admin", "global_admin", "own_group_token",
])
def test_group_channel_operations_allow_authorized_principals(
    client, db, notifier, operation, principal,
):
    group = create_group()
    channel = create_channel(
        group, config={"webhook_url": "https://example.com/original"},
    )
    channel.enabled = operation != "enable"
    channel.save()
    user = create_user(
        group=group,
        group_role="user_admin" if principal == "group_admin" else "editor",
        is_admin=principal in {"global_admin", "own_group_token"},
    )
    headers = (
        bounded_token_headers(user, group=group)
        if principal == "own_group_token" else jwt_headers(user)
    )

    response = channel_request(client, channel, operation, headers)

    assert response.status_code == 200, response.get_json()
    saved = NotificationChannel.get_by_id(channel.id)
    assert saved.team_id is None
    assert saved.group_id == group.id
    if operation == "update":
        assert saved.name == update_payload(channel)["name"]
        assert saved.config == update_payload(channel)["config"]
    elif operation == "delete":
        assert saved.deleted is True
    elif operation in {"enable", "disable"}:
        assert saved.enabled is (operation == "enable")
    if operation == "test":
        notifier.send.assert_called_once()
    else:
        notifier.send.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_team_viewer_keeps_read_and_test_access_only(client, db, notifier, operation):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group, group_role="viewer")
    add_user_to_team(team, user, role="viewer")
    channel = create_channel(
        group, team, config={"webhook_url": "https://example.com/original"},
    )

    response = channel_request(client, channel, operation, jwt_headers(user))

    expected = 200 if operation in {"get", "test"} else 403
    assert response.status_code == expected, response.get_json()
    if operation == "test":
        notifier.send.assert_called_once()
    else:
        notifier.send.assert_not_called()


@pytest.mark.parametrize("explicit_null", [False, True])
def test_team_channel_cannot_be_detached_by_update(client, db, explicit_null):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group, group_role="viewer")
    add_user_to_team(team, user, role="manager")
    channel = create_channel(
        group, team, config={"webhook_url": "https://example.com/original"},
    )
    link = attach_channel(create_route(team), channel)
    payload = update_payload(channel)
    if explicit_null:
        payload["team_id"] = None
    audit_count = AuditLog.select().count()

    response = client.put(
        f"/api/channels/{channel.id}", headers=jwt_headers(user), json=payload,
    )

    assert response.status_code == (400 if explicit_null else 200), response.get_json()
    saved = NotificationChannel.get_by_id(channel.id)
    assert saved.team_id == team.id
    assert saved.group_id == group.id
    assert AlertRouteChannel.get_by_id(link.id).channel_id == channel.id
    if explicit_null:
        assert saved.name == channel.name
        assert saved.config == channel.config
        assert AuditLog.select().count() == audit_count
    else:
        assert saved.name == payload["name"]
        assert saved.config == payload["config"]


def test_group_channel_can_keep_explicit_null_team(client, db):
    group = create_group()
    channel = create_channel(group)
    payload = {**update_payload(channel), "team_id": None}

    response = client.put(
        f"/api/channels/{channel.id}", json=payload,
        headers=jwt_headers(create_user(group=group)),
    )

    assert response.status_code == 200, response.get_json()
    saved = NotificationChannel.get_by_id(channel.id)
    assert saved.team_id is None
    assert saved.group_id == group.id
    assert saved.name == payload["name"]


@pytest.mark.parametrize("has_source_access,has_target_access", [
    (False, True), (True, False), (True, True),
])
@pytest.mark.parametrize("group_only", [False, True])
def test_channel_transfer_requires_source_and_destination_access(
    client, db, has_source_access, has_target_access, group_only,
):
    source_group, target_group = create_group(), create_group()
    source_team, target_team = create_team(source_group), create_team(target_group)
    channel = create_channel(source_group, None if group_only else source_team)
    user = create_user(
        group=source_group,
        group_role="editor" if has_source_access else "viewer",
    )
    if has_target_access:
        groups_repo.add_user_to_group(user.id, target_group.id, "viewer")
        add_user_to_team(target_team, user, role="manager")
    before = NotificationChannel.get_by_id(channel.id).__data__.copy()
    payload = {**update_payload(channel), "team_id": target_team.id}

    response = client.put(
        f"/api/channels/{channel.id}", json=payload, headers=jwt_headers(user),
    )

    saved = NotificationChannel.get_by_id(channel.id)
    if has_source_access and has_target_access:
        assert response.status_code == 200, response.get_json()
        assert saved.team_id == target_team.id
        assert saved.group_id == target_group.id
    else:
        assert response.status_code == 403, response.get_json()
        assert saved.__data__ == before


def test_missing_channel_still_returns_not_found(client, admin_headers):
    response = client.get("/api/channels/999999", headers=admin_headers)

    assert response.status_code == 404
