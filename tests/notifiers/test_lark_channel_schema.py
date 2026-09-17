from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.schemas.channels import (
    ChannelCreateSchema,
    ChannelUpdateSchema,
)
from app.notifiers.lark.notifier import LarkNotifier
from app.notifiers.registry import get_notifier, list_notifier_types
from app.services.channel_config import (
    CHANNEL_SECRET_PLACEHOLDER,
    merge_channel_config_secrets,
)
from app.services.serializers.channels import serialize_channel


def make_lark_schema(config):
    return ChannelCreateSchema(
        team_id=1,
        name="Feishu alerts",
        channel_type="lark",
        config=config,
    )


def test_lark_config_accepts_feishu_webhook_without_signing():
    schema = make_lark_schema({
        "webhook_url": (
            "https://open.feishu.cn/open-apis/bot/v2/hook/test"
        ),
    })

    assert schema.config == {
        "webhook_url": (
            "https://open.feishu.cn/open-apis/bot/v2/hook/test"
        ),
    }


def test_lark_config_accepts_larksuite_webhook_and_signing_secret():
    schema = make_lark_schema({
        "webhook_url": (
            " https://open.larksuite.com/open-apis/bot/v2/hook/test "
        ),
        "signing_secret": " secret ",
    })

    assert schema.config == {
        "webhook_url": (
            "https://open.larksuite.com/open-apis/bot/v2/hook/test"
        ),
        "signing_secret": "secret",
    }


@pytest.mark.parametrize("webhook_url", [None, "", "   "])
def test_lark_config_requires_webhook_url(webhook_url):
    with pytest.raises(ValidationError, match="requires webhook_url"):
        make_lark_schema({"webhook_url": webhook_url})


def test_lark_create_rejects_masked_secrets():
    with pytest.raises(ValidationError, match="only valid during updates"):
        make_lark_schema({
            "webhook_url": CHANNEL_SECRET_PLACEHOLDER,
            "signing_secret": CHANNEL_SECRET_PLACEHOLDER,
        })


def test_lark_update_accepts_masked_secrets():
    schema = ChannelUpdateSchema(
        team_id=1,
        name="Feishu alerts",
        channel_type="lark",
        config={
            "webhook_url": CHANNEL_SECRET_PLACEHOLDER,
            "signing_secret": CHANNEL_SECRET_PLACEHOLDER,
        },
    )

    assert schema.config["webhook_url"] == CHANNEL_SECRET_PLACEHOLDER
    assert schema.config["signing_secret"] == CHANNEL_SECRET_PLACEHOLDER


def test_lark_serializer_masks_webhook_and_signing_secret():
    channel = SimpleNamespace(
        id=1,
        group=None,
        team=None,
        name="Feishu alerts",
        channel_type="lark",
        config={
            "webhook_url": "https://open.feishu.cn/hook/secret",
            "signing_secret": "signing-secret",
        },
        enabled=True,
    )

    config = serialize_channel(channel)["config"]
    assert config == {
        "webhook_url": CHANNEL_SECRET_PLACEHOLDER,
        "signing_secret": CHANNEL_SECRET_PLACEHOLDER,
    }


def test_lark_secret_placeholders_restore_stored_values():
    result = merge_channel_config_secrets(
        "lark",
        {
            "webhook_url": CHANNEL_SECRET_PLACEHOLDER,
            "signing_secret": CHANNEL_SECRET_PLACEHOLDER,
        },
        "lark",
        {
            "webhook_url": "https://open.feishu.cn/hook/secret",
            "signing_secret": "stored-secret",
        },
    )

    assert result == {
        "webhook_url": "https://open.feishu.cn/hook/secret",
        "signing_secret": "stored-secret",
    }


def test_lark_channel_update_preserves_masked_secrets(
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
        name="Feishu production",
        channel_type="lark",
        config={
            "webhook_url": (
                "https://open.feishu.cn/open-apis/bot/v2/hook/stored"
            ),
            "signing_secret": "stored-signing-secret",
        },
    )

    response = client.put(
        f"/api/channels/{channel.id}",
        headers=auth_headers,
        json={
            "team_id": team.id,
            "name": "Feishu production",
            "channel_type": "lark",
            "enabled": True,
            "config": {
                "webhook_url": CHANNEL_SECRET_PLACEHOLDER,
                "signing_secret": CHANNEL_SECRET_PLACEHOLDER,
            },
        },
    )

    assert response.status_code == 200
    response_config = response.get_json()["config"]
    assert response_config == {
        "webhook_url": CHANNEL_SECRET_PLACEHOLDER,
        "signing_secret": CHANNEL_SECRET_PLACEHOLDER,
    }

    stored = channels_repo.get_channel(channel.id)
    assert stored.config == {
        "webhook_url": (
            "https://open.feishu.cn/open-apis/bot/v2/hook/stored"
        ),
        "signing_secret": "stored-signing-secret",
    }


def test_lark_notifier_is_registered():
    assert "lark" in list_notifier_types()
    assert isinstance(get_notifier("lark"), LarkNotifier)
