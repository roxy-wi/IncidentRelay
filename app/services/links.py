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

    parsed = urlsplit(value)

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

