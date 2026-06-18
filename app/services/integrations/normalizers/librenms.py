from urllib.parse import quote

from app.services.integrations.normalizers.common import (
    add_event_link_label,
    first_event_link,
    first_non_empty,
    make_dedup_key,
    normalize_event_link,
)


def normalize_librenms_status(value):
    """Convert LibreNMS alert state/status to IncidentRelay status."""
    if value is None:
        return "firing"

    status = str(value).strip().lower()

    if status in {
        "0",
        "ok",
        "clear",
        "cleared",
        "recover",
        "recovery",
        "recovered",
        "resolve",
        "resolved",
        "closed",
    }:
        return "resolved"

    return "firing"


def normalize_librenms_severity(value):
    """Map LibreNMS severity to IncidentRelay severity."""
    severity = str(value or "").strip().lower()

    mapping = {
        "critical": "critical",
        "crit": "critical",
        "error": "critical",
        "err": "critical",
        "high": "critical",

        "warning": "warning",
        "warn": "warning",
        "medium": "warning",

        "info": "info",
        "informational": "info",
        "notice": "info",
        "low": "info",
        "ok": "info",
        "clear": "info",
        "normal": "info",
    }

    return mapping.get(severity, severity or "info")


def build_librenms_device_link(librenms_url, hostname=None, device_id=None):
    """Build a LibreNMS device link when base URL and device identity exist."""
    base_url = normalize_event_link(librenms_url)

    if not base_url:
        return None

    identity = hostname or device_id

    if not identity:
        return None

    return f"{base_url.rstrip('/')}/device/device={quote(str(identity))}/"


def _as_label_value(value):
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        return value or None

    return str(value)


def _set_label(labels, key, value):
    value = _as_label_value(value)

    if value:
        labels.setdefault(key, value)


def _stable_dedup_labels(payload, labels):
    return {
        "hostname": first_non_empty(
            payload.get("hostname"),
            payload.get("display"),
            payload.get("sysName"),
            labels.get("hostname"),
            labels.get("display"),
            labels.get("sysName"),
        ),
        "device_id": first_non_empty(
            payload.get("device_id"),
            labels.get("device_id"),
        ),
        "rule": first_non_empty(
            payload.get("rule"),
            payload.get("name"),
            labels.get("rule"),
            labels.get("name"),
        ),
    }


def normalize_librenms(payload):
    """Normalize LibreNMS API transport payload."""
    labels = dict(payload.get("labels") or {})

    hostname = first_non_empty(
        payload.get("hostname"),
        payload.get("display"),
        payload.get("sysName"),
        labels.get("hostname"),
        labels.get("display"),
        labels.get("sysName"),
    )

    rule_name = first_non_empty(
        payload.get("rule"),
        payload.get("name"),
        labels.get("rule"),
        labels.get("name"),
    )

    title = first_non_empty(
        payload.get("title"),
        payload.get("subject"),
        rule_name,
        labels.get("alertname"),
        "LibreNMS alert",
    )

    message = first_non_empty(
        payload.get("message"),
        payload.get("msg"),
        payload.get("description"),
        payload.get("alert_notes"),
        "",
    )

    if not message:
        parts = []

        if hostname:
            parts.append(f"Device: {hostname}")

        if rule_name and rule_name != title:
            parts.append(f"Rule: {rule_name}")

        if payload.get("elapsed"):
            parts.append(f"Elapsed: {payload.get('elapsed')}")

        message = "\n".join(parts)

    external_id = first_non_empty(
        payload.get("external_id"),
        payload.get("uid"),
        payload.get("alert_uid"),
        payload.get("id"),
        payload.get("alert_id"),
    )

    state = first_non_empty(
        payload.get("state"),
        payload.get("status"),
    )

    severity = normalize_librenms_severity(
        first_non_empty(
            payload.get("severity"),
            labels.get("severity"),
        )
    )

    event_link = first_event_link(
        payload.get("event_link"),
        payload.get("event_url"),
        payload.get("alert_url"),
        payload.get("source_url"),
        payload.get("device_url"),
        payload.get("proc"),
        labels.get("event_link"),
        labels.get("event_url"),
        labels.get("alert_url"),
        labels.get("source_url"),
        labels.get("device_url"),
        build_librenms_device_link(
            payload.get("librenms_url"),
            hostname=hostname,
            device_id=payload.get("device_id"),
        ),
    )

    _set_label(labels, "hostname", hostname)
    _set_label(labels, "device_id", payload.get("device_id"))
    _set_label(labels, "ip", payload.get("ip"))
    _set_label(labels, "os", payload.get("os"))
    _set_label(labels, "type", payload.get("type"))
    _set_label(labels, "hardware", payload.get("hardware"))
    _set_label(labels, "version", payload.get("version"))
    _set_label(labels, "location", payload.get("location"))
    _set_label(labels, "rule", rule_name)
    _set_label(labels, "librenms_id", payload.get("id"))
    _set_label(labels, "librenms_uid", payload.get("uid"))
    _set_label(labels, "librenms_external_id", payload.get("external_id"))
    _set_label(labels, "librenms_state", payload.get("state"))
    _set_label(labels, "librenms_timestamp", payload.get("timestamp"))
    _set_label(labels, "librenms_severity", payload.get("severity"))

    add_event_link_label(labels, event_link)

    dedup_key = (
        payload.get("fingerprint")
        or make_dedup_key(
            "librenms",
            external_id,
            None if external_id else title,
            _stable_dedup_labels(payload, labels),
        )
    )

    return [
        {
            "source": "librenms",
            "team_slug": (
                payload.get("team")
                or labels.get("team")
                or labels.get("oncall_team")
            ),
            "external_id": external_id,
            "dedup_key": dedup_key,
            "title": title,
            "message": message or "",
            "severity": severity,
            "labels": labels,
            "payload": payload,
            "status": normalize_librenms_status(state),
        }
    ]
