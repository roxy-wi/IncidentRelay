from collections.abc import Mapping
from urllib.parse import urlsplit

from app.settings import Config


def build_alert_web_url(alert_or_id):
    """Build a public browser URL for alert details."""
    alert_id = getattr(alert_or_id, "id", alert_or_id)

    if not alert_id:
        return ""

    base_url = (Config.PUBLIC_BASE_URL or "").rstrip("/")

    if not base_url:
        return ""

    return f"{base_url}/alerts/{alert_id}"


SOURCE_EVENT_URL_KEYS = (
    "event_link",
    "event_url",
    "alert_url",
    "source_url",
    "generator_url",
    "dashboard_url",
    "panel_url",
    "problem_url",
    "trigger_url",
    "device_url",
    "sentry_url",
    "grafana_url",
)


def _normalize_external_url(value):
    """Return a safe absolute HTTP(S) URL."""
    if value is None:
        return ""

    value = str(value).strip()
    if not value:
        return ""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""

    return value


def build_source_event_url(alert):
    """Return the external source event URL for an alert or alert group."""
    direct_value = _normalize_external_url(getattr(alert, "event_link", None))
    if direct_value:
        return direct_value

    for attribute in ("labels", "common_labels"):
        labels = getattr(alert, attribute, None)

        if not isinstance(labels, dict):
            continue

        for key in SOURCE_EVENT_URL_KEYS:
            value = _normalize_external_url(labels.get(key))
            if value:
                return value

    return ""


def build_alert_resource_links(alert):
    """Extract distinct resource links, including from already stored payloads."""
    fields = [
        {"event_link": getattr(alert, "event_link", None)},
        getattr(alert, "labels", None),
        getattr(alert, "common_labels", None),
    ]
    payload = getattr(alert, "payload", None)
    if not isinstance(payload, Mapping):
        summary = getattr(alert, "payload_summary", None)
        payload = summary.get("latest_payload", summary) if isinstance(summary, Mapping) else {}
    if isinstance(payload, Mapping):
        # Grafana stores a webhook envelope containing this alert instance only.
        instances = payload.get("alerts")
        if isinstance(instances, list) and len(instances) == 1:
            instance = instances[0]
            if isinstance(instance, Mapping):
                fields.extend([instance.get("annotations"), instance.get("labels"), instance])
        fields.extend([
            payload.get("annotations"), payload.get("commonAnnotations"),
            payload.get("labels"), payload,
        ])
    fields = [item for item in fields if isinstance(item, Mapping)]

    def first_url(keys, excluded=()):
        for values in fields:
            for key in keys:
                url = _normalize_external_url(values.get(key))
                if url and url not in excluded:
                    return url
        return ""

    links = []
    seen = set()
    for kind, keys in (
        ("dashboard", ("dashboard_url", "dashboardURL")),
        ("panel", ("panel_url", "panelURL")),
        ("runbook", ("runbook_url", "runbookURL")),
    ):
        url = first_url(keys)
        if url and url not in seen:
            links.append({"kind": kind, "url": url})
            seen.add(url)

    source_keys = tuple(
        key for key in SOURCE_EVENT_URL_KEYS if key not in {"dashboard_url", "panel_url"}
    )
    source_url = first_url((*source_keys, "generatorURL"), excluded=seen)
    if source_url:
        links.insert(0, {"kind": "source", "url": source_url})
    return links

