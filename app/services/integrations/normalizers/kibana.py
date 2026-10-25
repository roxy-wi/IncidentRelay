"""Elastic Kibana Alerting 'for each alert' webhook action normalization.

A Kibana connector body is user-configurable: the recommended action template
transmits the rule ID, alert instance ID and space ID explicitly so both
triggered and recovered actions address the same concrete Alert occurrence.
"""

from app.services.integrations.normalizers.common import clean_string, first_non_empty
from app.services.integrations.normalizers.search_alerting_common import (
    alert_status,
    http_event_link,
    nested_value,
    provider_value,
    sanitized_labels,
    stable_search_key,
)
from app.services.severity import normalize_severity


def normalize_kibana(payload, *, route_id=None):
    """Convert one per-alert Kibana Webhook connector notification."""
    rule_id = provider_value(payload, "rule_id", ("rule", "id"))
    alert_id = provider_value(payload, "alert_id", ("alert", "id"))
    if not rule_id or not alert_id:
        raise ValueError("Kibana payload requires rule_id and alert_id")

    space_id = provider_value(payload, "space_id", ("rule", "spaceId")) or "default"
    rule_name = provider_value(payload, "rule_name", ("rule", "name"))
    reason = first_non_empty(
        payload.get("message"), payload.get("reason"),
        nested_value(payload, "context", "reason"),
    )
    labels = sanitized_labels(payload.get("labels"))
    labels.update({
        "kibana_rule_id": rule_id,
        "kibana_alert_id": alert_id,
        "kibana_space_id": space_id,
    })

    flapping = payload.get("flapping")
    if isinstance(flapping, bool):
        labels["kibana_flapping"] = "true" if flapping else "false"
    elif clean_string(flapping) in {"true", "false"}:
        labels["kibana_flapping"] = flapping

    event_link = http_event_link(payload.get("rule_url"), payload.get("event_link"), payload.get("url"))
    if event_link:
        labels["event_link"] = event_link

    team_slug = first_non_empty(payload.get("team"), labels.get("team"), labels.get("oncall_team"))
    title = first_non_empty(payload.get("title"), rule_name, "Kibana alert")
    message = first_non_empty(reason, title)
    severity = normalize_severity(first_non_empty(payload.get("severity"), labels.get("severity"), "warning"))
    state = first_non_empty(
        payload.get("status"), payload.get("state"), payload.get("action_group"),
        nested_value(payload, "alert", "actionGroup"),
    )
    return [{
        "source": "kibana",
        "team_slug": team_slug,
        "external_id": alert_id,
        "dedup_key": stable_search_key(
            "kibana", [space_id, rule_id, alert_id],
            route_id=route_id, team_slug=team_slug,
        ),
        "title": title,
        "message": message,
        "severity": severity,
        "labels": labels,
        "payload": dict(payload),
        "status": alert_status(state),
    }]
