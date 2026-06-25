from app.services.alerts.priority import alert_priority_slug
from app.services.routing.matcher.match_context import alert_rule_matches


def notification_rule_matches(group, rule, event_type):
    """Match a notification rule for one group event."""
    event_types = rule.event_types or []

    if isinstance(event_types, str):
        event_types = [event_types]

    if event_type not in event_types:
        return False

    return alert_rule_matches(
        group,
        rule,
        priority=alert_priority_slug(group),
    )
