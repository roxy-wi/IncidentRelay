from typing import Any, Mapping

from app.services.integrations.normalizers.common import (
    add_event_link_label,
    canonical_label_key,
    clean_string,
    first_event_link,
    first_non_empty,
    first_present,
    make_dedup_key,
    severity_from_priority,
    stable_labels,
)
from app.services.severity import normalize_severity


UP_STATUSES = {1, "1", "up", "ok", "healthy", "resolved", "recovered"}
DOWN_STATUSES = {0, "0", "down", "fail", "failed", "failing", "unhealthy"}
PENDING_STATUSES = {2, "2", "pending", "retrying"}
MAINTENANCE_STATUSES = {3, "3", "maintenance", "paused"}

STATUS_LABELS = {
    "resolved": "up",
    "firing": "down",
    "pending": "pending",
    "maintenance": "maintenance",
    "unknown": "unknown",
}


def _set_label(labels: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return

    if isinstance(value, bool):
        labels.setdefault(key, "true" if value else "false")
        return

    if isinstance(value, (str, int, float)):
        value = str(value).strip()
        if value:
            labels.setdefault(key, value)


def normalize_uptime_kuma_state(value: Any) -> str:
    """Return a descriptive Uptime Kuma state name."""

    normalized: Any = value
    if isinstance(value, str):
        normalized = value.strip().lower()

    if normalized in UP_STATUSES:
        return "resolved"
    if normalized in MAINTENANCE_STATUSES:
        return "maintenance"
    if normalized in PENDING_STATUSES:
        return "pending"
    if normalized in DOWN_STATUSES:
        return "firing"

    return "unknown"


def normalize_uptime_kuma_status(value: Any) -> str:
    """Map Uptime Kuma status to IncidentRelay firing/resolved lifecycle."""

    state = normalize_uptime_kuma_state(value)
    if state in {"resolved", "maintenance"}:
        return "resolved"
    return "firing"


def normalize_uptime_kuma_severity(value: Any, default: str = "critical") -> str:
    """Map Uptime Kuma tags or custom priority values to severity."""

    priority_severity = severity_from_priority(value)
    if priority_severity:
        return priority_severity

    normalized = str(value or "").strip().lower()
    return normalize_severity(normalized) or default


def normalize_uptime_kuma_tags(value: Any) -> dict[str, str]:
    """Convert Uptime Kuma monitor tags to matcher-friendly labels."""

    result: dict[str, str] = {}

    if value is None:
        return result

    if isinstance(value, Mapping):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]

    for item in items:
        name = None
        tag_value = None

        if isinstance(item, Mapping):
            name = first_non_empty(
                item.get("name"),
                item.get("tag_name"),
                item.get("key"),
            )
            tag_value = first_non_empty(
                item.get("value"),
                item.get("tag_value"),
            )
        else:
            text = clean_string(item)
            if not text:
                continue
            if ":" in text:
                name, tag_value = text.split(":", 1)
            elif "=" in text:
                name, tag_value = text.split("=", 1)
            else:
                name = text

        key = canonical_label_key(name)
        if not key:
            continue

        value_text = clean_string(tag_value) or "true"
        result.setdefault(f"uptime_kuma_tag_{key}", value_text)

        # Common routing tags are also exposed without the integration prefix.
        if key in {
            "team",
            "oncall_team",
            "service",
            "environment",
            "env",
            "severity",
            "priority",
            "region",
            "cluster",
        }:
            result.setdefault(key, value_text)

    return result


def _monitor_target(monitor: Mapping[str, Any]) -> str | None:
    url = clean_string(monitor.get("url"))
    if url:
        return url

    hostname = first_non_empty(
        monitor.get("hostname"),
        monitor.get("host"),
        monitor.get("dns_resolve_server"),
    )
    port = clean_string(monitor.get("port"))

    if hostname and port:
        return f"{hostname}:{port}"

    return clean_string(hostname)


def normalize_uptime_kuma(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize the standard Uptime Kuma Webhook notification payload."""

    monitor = dict(payload.get("monitor") or {})
    heartbeat = dict(payload.get("heartbeat") or {})
    labels = dict(payload.get("labels") or {})

    labels.update(normalize_uptime_kuma_tags(monitor.get("tags")))

    monitor_id = first_non_empty(
        monitor.get("id"),
        heartbeat.get("monitorID"),
        heartbeat.get("monitorId"),
        payload.get("monitor_id"),
    )
    monitor_name = first_non_empty(
        monitor.get("name"),
        payload.get("name"),
    )
    monitor_type = first_non_empty(
        monitor.get("type"),
        payload.get("monitor_type"),
    )
    target = _monitor_target(monitor)
    raw_status = first_present(
        heartbeat.get("status"),
        payload.get("status"),
    )
    normalized_state = normalize_uptime_kuma_state(raw_status)
    status = normalize_uptime_kuma_status(raw_status)

    _set_label(labels, "uptime_kuma_monitor_id", monitor_id)
    _set_label(labels, "uptime_kuma_monitor_name", monitor_name)
    _set_label(labels, "uptime_kuma_monitor_type", monitor_type)
    _set_label(labels, "uptime_kuma_status", STATUS_LABELS[normalized_state])
    _set_label(labels, "uptime_kuma_status_code", raw_status)
    _set_label(labels, "uptime_kuma_target", target)
    _set_label(labels, "uptime_kuma_hostname", monitor.get("hostname"))
    _set_label(labels, "uptime_kuma_port", monitor.get("port"))
    _set_label(labels, "uptime_kuma_ping_ms", heartbeat.get("ping"))
    _set_label(
        labels,
        "uptime_kuma_duration_seconds",
        heartbeat.get("duration"),
    )
    _set_label(
        labels,
        "uptime_kuma_local_datetime",
        first_non_empty(
            heartbeat.get("localDateTime"),
            heartbeat.get("time"),
        ),
    )

    event_link = first_event_link(
        payload.get("event_link"),
        payload.get("monitor_url"),
        monitor.get("dashboardURL"),
        monitor.get("dashboard_url"),
        target if str(target or "").startswith(("http://", "https://")) else None,
    )
    add_event_link_label(labels, event_link)

    title = first_non_empty(
        monitor_name,
        payload.get("title"),
        "Uptime Kuma notification",
    )
    message = first_non_empty(
        heartbeat.get("msg"),
        payload.get("msg"),
        payload.get("message"),
        target,
        "",
    )

    explicit_severity = first_non_empty(
        payload.get("severity"),
        monitor.get("severity"),
        labels.get("severity"),
        labels.get("priority"),
    )
    default_severity = "info" if not monitor and not heartbeat else "critical"
    severity = normalize_uptime_kuma_severity(
        explicit_severity,
        default=default_severity,
    )

    external_id = clean_string(monitor_id)
    if external_id:
        dedup_key = f"uptime-kuma:{external_id}"
    else:
        dedup_key = make_dedup_key(
            "uptime_kuma",
            external_id=first_non_empty(monitor_name, target),
            title=title,
            labels=stable_labels(
                labels,
                exclude={
                    "event_link",
                    "uptime_kuma_status",
                    "uptime_kuma_status_code",
                    "uptime_kuma_ping_ms",
                    "uptime_kuma_duration_seconds",
                    "uptime_kuma_local_datetime",
                },
            ),
        )

    return [{
        "source": "uptime_kuma",
        "team_slug": (
            labels.get("team")
            or labels.get("oncall_team")
            or payload.get("team")
        ),
        "external_id": external_id,
        "dedup_key": dedup_key,
        "title": title,
        "message": message or "",
        "severity": severity,
        "labels": labels,
        "annotations": {
            "uptime_kuma_state": STATUS_LABELS[normalized_state],
        },
        "payload": dict(payload),
        "status": status,
    }]


__all__ = [
    "normalize_uptime_kuma",
    "normalize_uptime_kuma_state",
    "normalize_uptime_kuma_status",
    "normalize_uptime_kuma_severity",
    "normalize_uptime_kuma_tags",
]
