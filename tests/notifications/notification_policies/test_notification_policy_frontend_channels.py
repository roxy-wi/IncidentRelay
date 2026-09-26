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


def test_notification_policy_editor_exposes_all_common_filters():
    for field in (
        "common-priority",
        "common-severity",
        "common-source",
        "common-service",
        "common-environment",
        "common-criticality",
        "common-tier",
    ):
        assert field in SOURCE


def test_notification_policy_editor_merges_common_and_advanced_matchers():
    assert "notificationPolicyCommonMatcherState" in SOURCE
    assert "notificationPolicyAdvancedMatchers" in SOURCE
    assert "mergeNotificationPolicyCommonMatchers" in SOURCE
    assert "value: notificationPolicyAdvancedMatchers(rule.matchers || {})" in SOURCE
    assert "matchers: mergeNotificationPolicyCommonMatchers(" in SOURCE


def test_notification_policy_common_filters_use_existing_matcher_fields():
    assert 'result.priority = priorities;' in SOURCE
    assert 'result.severity = severities;' in SOURCE
    assert 'result.source = sources;' in SOURCE
    assert 'fields["service.id"] = services;' in SOURCE
    assert 'fields["service.environment"] = environments;' in SOURCE
    assert 'fields["service.criticality"] = criticalities;' in SOURCE
    assert 'fields["service.tier"] = tiers;' in SOURCE
