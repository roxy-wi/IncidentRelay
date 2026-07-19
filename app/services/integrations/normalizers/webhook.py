import json
from copy import deepcopy

from app.services.integrations.normalizers.common import (
    add_event_link_label,
    first_event_link,
    first_non_empty,
    make_dedup_key,
)
from app.services.severity import normalize_severity


PAGERDUTY_EVENT_ACTIONS = {"trigger", "acknowledge", "resolve"}


def is_pagerduty_events_v2(payload):
    """Return True for a supported PagerDuty Events API v2 alert event."""

    if not isinstance(payload, dict):
        return False

    action = str(payload.get("event_action") or "").strip().lower()
    return action in PAGERDUTY_EVENT_ACTIONS


def _clean_string(value):
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def _label_value(value):
    """Convert custom detail values into matcher-friendly label values."""

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _sanitized_payload(payload):
    """Copy the source payload without persisting the secret routing key."""

    result = deepcopy(payload)

    if result.get("routing_key"):
        result["routing_key"] = "[REDACTED]"

    return result


def _pagerduty_labels(payload, event_payload, action):
    labels = dict(payload.get("labels") or {})
    labels.setdefault("pagerduty_event_action", action)
    labels.setdefault("pagerduty_format", "events_api_v2")

    for key in ("source", "component", "group", "class"):
        value = _clean_string(event_payload.get(key))

        if value is not None:
            labels.setdefault(key, value)

    custom_details = event_payload.get("custom_details") or {}

    if isinstance(custom_details, dict):
        for key, value in custom_details.items():
            key = _clean_string(key)

            if not key or key in labels:
                continue

            value = _label_value(value)

            if value is not None:
                labels[key] = value

    client = _clean_string(payload.get("client"))

    if client:
        labels.setdefault("pagerduty_client", client)

    return labels


def _pagerduty_event_link(payload):
    links = payload.get("links") or []
    link_values = []

    if isinstance(links, list):
        for item in links:
            if isinstance(item, dict):
                link_values.append(item.get("href"))

    return first_event_link(
        *link_values,
        payload.get("client_url"),
    )


def _normalize_pagerduty_events_v2(payload):
    action = str(payload.get("event_action") or "").strip().lower()
    event_payload = payload.get("payload") or {}

    if not isinstance(event_payload, dict):
        event_payload = {}

    labels = _pagerduty_labels(payload, event_payload, action)
    event_link = _pagerduty_event_link(payload)
    add_event_link_label(labels, event_link)

    dedup_key = _clean_string(payload.get("dedup_key"))
    summary = _clean_string(event_payload.get("summary"))
    source = _clean_string(event_payload.get("source"))

    title = summary or (
        f"PagerDuty event {dedup_key}"
        if dedup_key
        else "PagerDuty webhook event"
    )
    title = title[:255]

    if not dedup_key:
        dedup_key = make_dedup_key(
            "webhook",
            source,
            title,
            {
                "component": labels.get("component"),
                "group": labels.get("group"),
                "class": labels.get("class"),
            },
        )

    custom_details = event_payload.get("custom_details") or {}

    if not isinstance(custom_details, dict):
        custom_details = {}

    message = first_non_empty(
        event_payload.get("message"),
        event_payload.get("description"),
        custom_details.get("message"),
        custom_details.get("description"),
        custom_details.get("details"),
    ) or ""

    raw_severity = event_payload.get("severity")
    severity = normalize_severity(raw_severity) or "info"

    team_slug = first_non_empty(
        payload.get("team"),
        labels.get("team"),
        labels.get("oncall_team"),
        custom_details.get("team"),
        custom_details.get("oncall_team"),
    )

    status = {
        "trigger": "firing",
        "acknowledge": "acknowledged",
        "resolve": "resolved",
    }[action]

    return [
        {
            "source": "webhook",
            "team_slug": team_slug,
            "external_id": dedup_key,
            "dedup_key": dedup_key,
            "title": title,
            "message": str(message),
            "severity": severity,
            "labels": labels,
            "payload": _sanitized_payload(payload),
            "status": status,
            "lifecycle_action": action,
            "integration_format": "pagerduty_events_api_v2",
        }
    ]


def normalize_webhook(payload):
    """Normalize a generic or PagerDuty Events API v2 webhook payload."""

    if is_pagerduty_events_v2(payload):
        return _normalize_pagerduty_events_v2(payload)

    labels = dict(payload.get("labels") or {})

    event_link = first_event_link(
        payload.get("event_link"),
        payload.get("event_url"),
        payload.get("alert_url"),
        payload.get("source_url"),
        payload.get("dashboard_url"),
        payload.get("runbook_url"),
        labels.get("event_link"),
        labels.get("event_url"),
        labels.get("alert_url"),
        labels.get("source_url"),
        labels.get("dashboard_url"),
        labels.get("runbook_url"),
    )

    add_event_link_label(labels, event_link)

    title = payload.get("title") or "Webhook alert"

    return [
        {
            "source": "webhook",
            "team_slug": payload.get("team") or labels.get("team") or labels.get("oncall_team"),
            "external_id": payload.get("external_id"),
            "dedup_key": payload.get("fingerprint")
                         or make_dedup_key("webhook", payload.get("external_id"), title, labels),
            "title": title,
            "message": payload.get("message") or "",
            "severity": normalize_severity(payload.get("severity")) or "info",
            "labels": labels,
            "payload": _sanitized_payload(payload),
            "status": payload.get("status") or "firing",
        }
    ]
