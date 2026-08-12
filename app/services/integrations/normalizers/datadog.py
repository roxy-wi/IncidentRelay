from app.services.integrations.normalizers.common import (
    add_event_link_label,
    canonical_label_key,
    clean_string,
    first_event_link,
    first_non_empty,
    make_dedup_key,
    normalize_label_value,
    severity_from_priority,
    stable_labels,
)
from app.services.severity import normalize_severity


RESOLVED_TRANSITIONS = {
    "ok",
    "recover",
    "recovered",
    "recovery",
    "resolve",
    "resolved",
    "success",
}


def _canonical_payload(payload):
    result = {}

    for key, value in (payload or {}).items():
        normalized = canonical_label_key(key)
        if not normalized:
            continue

        if normalized not in result or (
            result[normalized] is None and value is not None
        ):
            result[normalized] = value

    return result


def _get(data, *names):
    for name in names:
        value = data.get(canonical_label_key(name))
        if value is not None:
            return value

    return None


def normalize_datadog_status(transition, alert_type=None):
    """Convert Datadog transitions to IncidentRelay firing/resolved state."""

    transition = clean_string(transition)
    normalized = str(transition or "").lower().replace("_", " ").replace("-", " ")

    normalized = " ".join(normalized.split())

    if normalized in RESOLVED_TRANSITIONS:
        return "resolved"

    if not normalized and str(alert_type or "").strip().lower() == "success":
        return "resolved"

    return "firing"


def normalize_datadog_severity(explicit, alert_type=None, priority=None):
    """Map Datadog severity/type/monitor priority to IncidentRelay severity."""

    explicit = clean_string(explicit)
    if explicit:
        return normalize_severity(explicit) or "info"

    priority_severity = severity_from_priority(priority)
    if priority_severity:
        return priority_severity

    return normalize_severity(alert_type) or "info"


def normalize_datadog_tags(value):
    """Convert Datadog tags or alert scope into flat matcher-friendly labels."""

    labels = {}

    if value is None:
        return labels

    if isinstance(value, dict):
        for key, item in value.items():
            key = clean_string(key)
            item = normalize_label_value(item)
            if key and item is not None:
                labels[key] = item
        return labels

    if isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = str(value).split(",")

    for item in items:
        if isinstance(item, dict):
            labels.update(normalize_datadog_tags(item))
            continue

        item = clean_string(item)
        if not item:
            continue

        if ":" in item:
            key, tag_value = item.split(":", 1)
            key = key.strip()
            tag_value = tag_value.strip()
            if key:
                labels.setdefault(key, tag_value)
        else:
            labels.setdefault(item, "true")

    return labels


def normalize_datadog(payload):
    """Normalize a Datadog Webhooks integration payload."""

    data = _canonical_payload(payload)
    labels = {}

    raw_labels = _get(data, "labels")
    if isinstance(raw_labels, dict):
        for key, value in raw_labels.items():
            key = clean_string(key)
            value = normalize_label_value(value)
            if key and value is not None:
                labels[key] = value

    labels.update(normalize_datadog_tags(_get(data, "tags")))
    labels.update(normalize_datadog_tags(_get(data, "alert_scope", "scope")))

    alert_id = clean_string(_get(data, "alert_id", "monitor_id"))
    event_id = clean_string(_get(data, "id", "event_id"))
    alert_cycle_key = clean_string(_get(data, "alert_cycle_key"))
    aggreg_key = clean_string(_get(data, "aggreg_key", "aggregation_key"))
    transition = clean_string(_get(data, "alert_transition", "transition"))
    alert_type = clean_string(_get(data, "alert_type", "event_alert_type"))
    priority = clean_string(_get(data, "alert_priority", "priority"))
    alert_scope = clean_string(_get(data, "alert_scope", "scope"))
    hostname = clean_string(_get(data, "hostname", "host"))
    event_type = clean_string(_get(data, "event_type"))
    metric = clean_string(_get(data, "alert_metric", "metric"))

    fixed_labels = {
        "datadog_alert_id": alert_id,
        "datadog_event_id": event_id,
        "datadog_alert_cycle_key": alert_cycle_key,
        "datadog_aggreg_key": aggreg_key,
        "datadog_alert_transition": transition,
        "datadog_alert_type": alert_type,
        "datadog_alert_priority": priority,
        "datadog_scope": alert_scope,
        "datadog_event_type": event_type,
        "datadog_metric": metric,
        "host": hostname,
    }

    for key, value in fixed_labels.items():
        if value is not None:
            labels.setdefault(key, value)

    event_link = first_event_link(
        _get(data, "link", "event_link", "event_url", "url"),
        _get(data, "incident_url"),
    )
    add_event_link_label(labels, event_link)

    title = first_non_empty(
        _get(data, "alert_title"),
        _get(data, "event_title"),
        _get(data, "title"),
        "Datadog alert",
    )

    message = first_non_empty(
        _get(data, "text_only_msg"),
        _get(data, "event_msg"),
        _get(data, "message"),
        _get(data, "alert_status"),
        "",
    )

    severity = normalize_datadog_severity(
        _get(data, "severity"),
        alert_type=alert_type,
        priority=priority,
    )

    status = normalize_datadog_status(
        transition,
        alert_type=alert_type,
    )

    external_id = first_non_empty(
        alert_cycle_key,
        aggreg_key,
        event_id,
        alert_id,
    )

    dedup_key = first_non_empty(
        alert_cycle_key,
        aggreg_key,
        _get(data, "dedup_key", "fingerprint"),
    )

    if not dedup_key:
        dedup_key = make_dedup_key(
            "datadog",
            external_id=alert_id or event_id,
            title=title,
            labels=stable_labels(
                labels,
                exclude={
                    "event_link",
                    "datadog_alert_transition",
                    "datadog_alert_status",
                },
            ),
        )

    team_slug = first_non_empty(
        _get(data, "team", "oncall_team"),
        labels.get("team"),
        labels.get("oncall_team"),
    )

    return [{
        "source": "datadog",
        "team_slug": team_slug,
        "external_id": external_id,
        "dedup_key": dedup_key,
        "title": str(title)[:255],
        "message": str(message or ""),
        "severity": severity,
        "labels": labels,
        "payload": dict(payload or {}),
        "status": status,
    }]
