from urllib.parse import urlparse

from app.services.integrations.normalizers.common import (
    first_event_link,
    add_event_link_label,
    make_dedup_key,
    first_non_empty,
)


def _extract_hostname(value):
    """Return hostname-like value from Alertmanager labels such as instance=host:port."""

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    # Erlang/RabbitMQ style node value: rabbit@rabbitmq-cloud-server
    if "@" in value and "://" not in value and "/" not in value:
        value = value.rsplit("@", 1)[1].strip()

    # URL-like value.
    if "://" in value:
        parsed = urlparse(value)
        return parsed.hostname or value

    # IPv6 with port: [::1]:9100
    if value.startswith("["):
        end = value.find("]")
        if end > 0:
            return value[1:end]

    # Strip path if someone sends instance=host:port/path.
    if "/" in value:
        value = value.split("/", 1)[0].strip()

    # Common Prometheus instance format: host:port or ip:port.
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)

        if host and port.isdigit():
            return host

    return value


def _add_hostname_label(labels):
    """Add hostname label for Alertmanager alerts without overwriting explicit hostname."""

    hostname = first_non_empty(
        labels.get("hostname"),
        labels.get("host"),
        labels.get("nodename"),
    )

    hostname = _extract_hostname(hostname)

    if not hostname:
        hostname = first_non_empty(
            _extract_hostname(labels.get("node")),
            _extract_hostname(labels.get("instance")),
            _extract_hostname(labels.get("ip")),
        )

    if hostname:
        labels.setdefault("hostname", hostname)

    return labels


def normalize_alertmanager(payload):
    """
    Normalize Prometheus Alertmanager payload.
    """

    result = []
    for item in payload.get("alerts", []):
        labels = dict(item.get("labels") or {})
        annotations = item.get("annotations", {})

        _add_hostname_label(labels)
        event_link = first_event_link(
            annotations.get("event_link"),
            annotations.get("event_url"),
            annotations.get("alert_url"),
            annotations.get("source_url"),
            annotations.get("dashboard_url"),
            annotations.get("panel_url"),
            annotations.get("runbook_url"),
            item.get("generatorURL"),
            item.get("dashboardURL"),
            item.get("panelURL"),
            item.get("silenceURL"),
            payload.get("externalURL"),
        )

        add_event_link_label(labels, event_link)

        if item.get("generatorURL"):
            labels.setdefault("generator_url", item.get("generatorURL"))

        if payload.get("externalURL"):
            labels.setdefault("alertmanager_url", payload.get("externalURL"))

        title = annotations.get("summary") or labels.get("alertname") or "Alertmanager alert"
        message = annotations.get("description") or annotations.get("message") or ""
        external_id = item.get("fingerprint") or labels.get("alertname")
        result.append({
            "source": "alertmanager",
            "team_slug": labels.get("team") or labels.get("oncall_team") or payload.get("team"),
            "external_id": external_id,
            "dedup_key": item.get("fingerprint") or make_dedup_key("alertmanager", external_id, title, labels),
            "title": title,
            "message": message,
            "severity": labels.get("severity"),
            "labels": labels,
            "payload": item,
            "status": item.get("status") or payload.get("status", "firing"),
        })
    return result
