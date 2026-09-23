"""Frontend contract guards for Notification Policy channel editing."""

from pathlib import Path


SOURCE = Path("app/static/js/pages/notification_policies.js").read_text(encoding="utf-8")


def test_notification_policy_editor_keeps_disabled_channels_visible():
    assert "notificationPolicyChannelsCache = asArray(channels);" in SOURCE
    assert "channel.enabled !== false" not in SOURCE
    assert 'notification_policies.status.disabled' in SOURCE


def test_notification_policy_editor_preserves_rule_embedded_channels():
    assert "asArray(rule.channels).forEach" in SOURCE
    assert "channelsById" in SOURCE
    assert 'notification_policies.rules.no_channels' in SOURCE
