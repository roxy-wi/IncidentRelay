from __future__ import annotations

from collections.abc import Mapping

from app.services.integrations.normalizers.common import (
    add_event_link_label,
    canonical_label_key,
    clean_string,
    first_event_link,
    first_non_empty,
    normalize_label_value,
)


RESOLVED_NOTIFICATION_TYPES = {"recovery"}
ACK_NOTIFICATION_TYPES = {"acknowledgement", "acknowledgment", "ack"}
IGNORED_NOTIFICATION_TYPES = {
    "custom",
    "downtimecancelled",
    "downtimestart",
    "downtimestop",
    "flappingdisabled",
    "flappingstart",
    "flappingstop",
}

SERVICE_SEVERITIES = {
    "critical": "critical",
    "warning": "warning",
    "unknown": "high",
    "ok": "info",
}

HOST_SEVERITIES = {
    "down": "critical",
    "unreachable": "high",
    "up": "info",
}


def _canonical_payload(payload):
    result = {}
    for key, value in (payload or {}).items():
        normalized = canonical_label_key(key)
        if normalized and normalized not in result:
            result[normalized] = value
    return result


def _get(data, *names):
    for name in names:
        value = data.get(canonical_label_key(name))
        if value is not None:
            return value
    return None


def _normalize_notification_type(value):
    value = clean_string(value)
    if not value:
        return None
    return canonical_label_key(value).replace("_", "")


def normalize_nagios_labels(value):
    """Normalize optional custom labels into matcher-friendly scalar values."""
    labels = {}
    if not isinstance(value, Mapping):
        return labels

    for key, item in value.items():
        key = canonical_label_key(key)
        if not key:
            continue
        item = normalize_label_value(item)
        if item is not None:
            labels[key] = item

    return labels


def normalize_nagios_status(notification_type=None, service_state=None, host_state=None):
    """Map Nagios notification/state values to IncidentRelay alert status."""
    notification_type = _normalize_notification_type(notification_type)
    if notification_type in RESOLVED_NOTIFICATION_TYPES:
        return "resolved"

    service_state = str(service_state or "").strip().lower()
    host_state = str(host_state or "").strip().lower()

    if service_state == "ok" or (not service_state and host_state == "up"):
        return "resolved"

    return "firing"


def normalize_nagios_severity(service_state=None, host_state=None):
    """Map Nagios host/service states to IncidentRelay severity."""
    service_state = str(service_state or "").strip().lower()
    if service_state:
        return SERVICE_SEVERITIES.get(service_state, "warning")

    host_state = str(host_state or "").strip().lower()
    if host_state:
        return HOST_SEVERITIES.get(host_state, "warning")

    return "warning"


def nagios_lifecycle_action(notification_type=None, service_state=None, host_state=None):
    """Return trigger/resolve/acknowledge/ignore for one Nagios notification."""
    normalized = _normalize_notification_type(notification_type)

    if normalized in ACK_NOTIFICATION_TYPES:
        return "acknowledge"

    if normalized in IGNORED_NOTIFICATION_TYPES:
        return "ignore"

    if normalize_nagios_status(notification_type, service_state, host_state) == "resolved":
        return "resolve"

    return "trigger"


def normalize_nagios(payload):
    """Normalize Nagios Core/XI host or service notification payloads."""
    data = _canonical_payload(payload)

    host_name = clean_string(
        first_non_empty(
            _get(data, "host_name", "hostname", "host"),
            _get(data, "host_alias"),
        )
    )
    host_alias = clean_string(_get(data, "host_alias"))
    host_address = clean_string(_get(data, "host_address", "address"))
    service_description = clean_string(
        _get(data, "service_description", "service_desc", "service")
    )
    notification_type = clean_string(
        _get(data, "notification_type", "notificationtype")
    )
    host_state = clean_string(_get(data, "host_state", "hoststate"))
    service_state = clean_string(_get(data, "service_state", "servicestate"))
    state_type = clean_string(
        first_non_empty(
            _get(data, "service_state_type", "servicestatetype"),
            _get(data, "host_state_type", "hoststatetype"),
            _get(data, "state_type"),
        )
    )

    object_type = "service" if service_description else "host"
    state = service_state if object_type == "service" else host_state

    labels = normalize_nagios_labels(_get(data, "labels"))
    fixed_labels = {
        "nagios_object_type": object_type,
        "nagios_host": host_name,
        "nagios_host_alias": host_alias,
        "nagios_host_address": host_address,
        "nagios_service": service_description,
        "nagios_state": state,
        "nagios_state_type": state_type,
        "nagios_notification_type": notification_type,
    }
    for key, value in fixed_labels.items():
        if value is not None:
            labels.setdefault(key, value)

    event_link = first_event_link(
        _get(data, "event_link", "url", "link"),
        _get(data, "service_action_url", "serviceactionurl"),
        _get(data, "host_action_url", "hostactionurl"),
        _get(data, "service_notes_url", "servicenotesurl"),
        _get(data, "host_notes_url", "hostnotesurl"),
    )
    add_event_link_label(labels, event_link)

    output = clean_string(
        first_non_empty(
            _get(data, "service_output", "serviceoutput"),
            _get(data, "host_output", "hostoutput"),
            _get(data, "output"),
        )
    )
    long_output = clean_string(
        first_non_empty(
            _get(data, "long_service_output", "longserviceoutput"),
            _get(data, "long_host_output", "longhostoutput"),
            _get(data, "long_output"),
        )
    )
    message_parts = [part for part in (output, long_output) if part]
    message = "\n".join(message_parts)

    title = clean_string(_get(data, "title", "subject"))
    if not title:
        if object_type == "service":
            title = f"{state or 'UNKNOWN'}: {service_description or 'Service'} on {host_name or 'unknown host'}"
        else:
            title = f"{state or 'UNKNOWN'}: {host_name or host_alias or 'Nagios host'}"

    external_id = (
        f"service:{host_name}:{service_description}"
        if object_type == "service"
        else f"host:{host_name}"
    )
    dedup_key = clean_string(_get(data, "dedup_key")) or f"nagios:{external_id}"

    status = normalize_nagios_status(notification_type, service_state, host_state)
    lifecycle_action = nagios_lifecycle_action(
        notification_type,
        service_state,
        host_state,
    )
    severity = normalize_nagios_severity(service_state, host_state)

    team_slug = first_non_empty(
        _get(data, "team", "team_slug", "oncall_team"),
        labels.get("team"),
        labels.get("oncall_team"),
    )

    return [{
        "source": "nagios",
        "team_slug": team_slug,
        "external_id": external_id,
        "dedup_key": dedup_key,
        "title": title[:255],
        "message": message,
        "severity": severity,
        "labels": labels,
        "payload": dict(payload or {}),
        "status": status,
        "lifecycle_action": lifecycle_action,
    }]
