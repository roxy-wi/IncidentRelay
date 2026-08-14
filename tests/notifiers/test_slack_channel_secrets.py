from types import SimpleNamespace

from app.services.channel_config import (
    CHANNEL_SECRET_PLACEHOLDER,
    merge_channel_config_secrets,
)
from app.services.serializers.channels import serialize_channel


def test_slack_serializer_masks_all_secrets():
    channel = SimpleNamespace(
        id=1,
        group=None,
        team=None,
        name="Slack",
        channel_type="slack",
        config={
            "mode": "bot_api",
            "connection_mode": "socket_mode",
            "bot_token": "xoxb-secret",
            "app_token": "xapp-secret",
            "signing_secret": "signing-secret",
            "channel_id": "C1",
        },
        enabled=True,
    )

    config = serialize_channel(channel)["config"]
    assert config["bot_token"] == CHANNEL_SECRET_PLACEHOLDER
    assert config["app_token"] == CHANNEL_SECRET_PLACEHOLDER
    assert config["signing_secret"] == CHANNEL_SECRET_PLACEHOLDER
    assert config["channel_id"] == "C1"


def test_channel_update_secret_placeholders_restore_stored_values():
    result = merge_channel_config_secrets(
        "slack",
        {
            "bot_token": CHANNEL_SECRET_PLACEHOLDER,
            "app_token": CHANNEL_SECRET_PLACEHOLDER,
        },
        "slack",
        {
            "bot_token": "xoxb-secret",
            "app_token": "xapp-secret",
        },
    )
    assert result == {
        "bot_token": "xoxb-secret",
        "app_token": "xapp-secret",
    }


def test_slack_channel_update_preserves_masked_secrets(
    client,
    auth_headers,
    db,
):
    from app.modules.db import channels_repo
    from tests.factories import create_group, create_team

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    channel = channels_repo.create_channel(
        team_id=team.id,
        group_id=group.id,
        name="Slack production",
        channel_type="slack",
        config={
            "mode": "bot_api",
            "connection_mode": "socket_mode",
            "bot_token": "xoxb-stored-token",
            "app_token": "xapp-stored-token",
            "channel_id": "C0123456789",
        },
    )

    response = client.put(
        f"/api/channels/{channel.id}",
        headers=auth_headers,
        json={
            "team_id": team.id,
            "name": "Slack production",
            "channel_type": "slack",
            "enabled": True,
            "config": {
                "mode": "bot_api",
                "connection_mode": "socket_mode",
                "bot_token": CHANNEL_SECRET_PLACEHOLDER,
                "app_token": CHANNEL_SECRET_PLACEHOLDER,
                "channel_id": "C0123456789",
            },
        },
    )

    assert response.status_code == 200
    response_config = response.get_json()["config"]
    assert response_config["bot_token"] == CHANNEL_SECRET_PLACEHOLDER
    assert response_config["app_token"] == CHANNEL_SECRET_PLACEHOLDER

    stored = channels_repo.get_channel(channel.id)
    assert stored.config["bot_token"] == "xoxb-stored-token"
    assert stored.config["app_token"] == "xapp-stored-token"


def test_slack_channel_update_does_not_expose_secret_merge_exception(
    client,
    auth_headers,
    db,
):
    from app.modules.db import channels_repo
    from tests.factories import create_group, create_team

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    channel = channels_repo.create_channel(
        team_id=team.id,
        group_id=group.id,
        name="Slack production",
        channel_type="slack",
        config={
            "mode": "bot_api",
            "connection_mode": "socket_mode",
            "bot_token": "xoxb-stored-token",
            "app_token": "xapp-stored-token",
            "channel_id": "C0123456789",
        },
    )

    response = client.put(
        f"/api/channels/{channel.id}",
        headers=auth_headers,
        json={
            "team_id": team.id,
            "name": "Slack production",
            "channel_type": "slack",
            "enabled": True,
            "config": {
                "mode": "bot_api",
                "connection_mode": "http",
                "bot_token": CHANNEL_SECRET_PLACEHOLDER,
                "signing_secret": CHANNEL_SECRET_PLACEHOLDER,
                "channel_id": "C0123456789",
            },
        },
    )

    body = response.get_data(as_text=True)

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "validation_error",
        "message": "Channel secret configuration is invalid.",
    }
    assert "signing_secret" not in body
    assert "stored value" not in body
    assert "ValueError" not in body
