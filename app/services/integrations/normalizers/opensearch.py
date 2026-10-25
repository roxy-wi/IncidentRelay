"""OpenSearch Alerting custom webhook action payload normalization.

OpenSearch custom webhook bodies are configured by the operator using Mustache.
Monitor + trigger (+ bucket key for per-bucket alerts) identify a signal, not
its notification delivery or its mutable title/severity/state.
"""

from app.services.integrations.normalizers.common import first_non_empty, normalize_label_value
from app.services.integrations.normalizers.search_alerting_common import (
    alert_status,
    http_event_link,
    nested_value,
    provider_value,
    sanitized_labels,
    stable_search_key,
)
from app.services.severity import normalize_severity


OPENSEARCH_SEVERITIES = {
    "1": "critical", "2": "high", "3": "medium",
    "4": "warning", "5": "info",
}


def normalize_opensearch(payload, *, route_id=None):
    """Convert one query-level or per-bucket custom webhook into one Alert."""
    monitor_id = provider_value(
        payload, "monitor_id", ("monitor", "id"), ("ctx", "monitor", "id"),
    )
    trigger_id = provider_value(
        payload, "trigger_id", ("trigger", "id"), ("ctx", "trigger", "id"),
    )
    if not monitor_id or not trigger_id:
        raise ValueError("OpenSearch payload requires monitor_id and trigger_id")

    monitor_name = provider_value(
        payload, "monitor_name", ("monitor", "name"), ("ctx", "monitor", "name"),
    )
    trigger_name = provider_value(
        payload, "trigger_name", ("trigger", "name"), ("ctx", "trigger", "name"),
    )
    alert_id = provider_value(payload, "alert_id", ("alert", "id"), ("ctx", "alert", "id"))
    bucket_key = provider_value(
        payload, "bucket_key", ("bucket", "key"), ("ctx", "alert", "bucket_key"),
    )
    if bucket_key is None:
        raw_bucket_keys = first_non_empty(
            payload.get("bucket_keys"), nested_value(payload, "ctx", "alert", "bucket_keys"),
        )
        if isinstance(raw_bucket_keys, (list, dict)):
            bucket_key = normalize_label_value(raw_bucket_keys)

    labels = sanitized_labels(payload.get("labels"))
    labels.update({
        "opensearch_monitor_id": monitor_id,
        "opensearch_trigger_id": trigger_id,
    })
    if monitor_name:
        labels["opensearch_monitor_name"] = monitor_name
    if trigger_name:
        labels["opensearch_trigger_name"] = trigger_name
    if bucket_key:
        labels["opensearch_bucket_key"] = bucket_key
    if alert_id:
        labels["opensearch_alert_id"] = alert_id

    team_slug = first_non_empty(payload.get("team"), labels.get("team"), labels.get("oncall_team"))
    severity_raw = first_non_empty(
        payload.get("severity"),
        nested_value(payload, "trigger", "severity"),
        nested_value(payload, "ctx", "trigger", "severity"),
        labels.get("severity"),
    )
    severity = OPENSEARCH_SEVERITIES.get(str(severity_raw), normalize_severity(severity_raw or "warning"))
    title = first_non_empty(payload.get("title"), trigger_name, monitor_name, "OpenSearch alert")
    message = first_non_empty(payload.get("message"), payload.get("description"), title)
    event_link = http_event_link(payload.get("event_link"), payload.get("monitor_url"), payload.get("url"))
    if event_link:
        labels["event_link"] = event_link

    state = first_non_empty(
        payload.get("status"), payload.get("state"),
        nested_value(payload, "alert", "state"),
        nested_value(payload, "ctx", "alert", "state"),
    )
    return [{
        "source": "opensearch",
        "team_slug": team_slug,
        "external_id": alert_id or f"{monitor_id}:{trigger_id}",
        "dedup_key": stable_search_key(
            "opensearch", [monitor_id, trigger_id, bucket_key or ""],
            route_id=route_id, team_slug=team_slug,
        ),
        "title": title,
        "message": message,
        "severity": severity,
        "labels": labels,
        "payload": dict(payload),
        "status": alert_status(state),
    }]
