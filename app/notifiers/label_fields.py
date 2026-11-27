"""Labels and annotations worth showing on a notification.

IncidentRelay stores them on the alert group. Only values the alert
actually carries are returned.
"""


LABEL_FIELDS = (
    ("environment", "Environment"),
    ("cluster", "Cluster"),
    ("namespace", "Namespace"),
    ("tenant", "Project"),
    ("server_name", "Server"),
    ("instance", "Address"),
    ("device", "Device"),
)


def alert_labels(alert):
    """Return the label dict from an alert group or a child alert."""

    for name in ("common_labels", "labels"):
        value = getattr(alert, name, None)

        if isinstance(value, dict):
            return value

    return {}


def present_label_fields(alert):
    """Return ``(title, value)`` for labels that this alert actually has."""

    labels = alert_labels(alert)
    rows = []

    for key, title in LABEL_FIELDS:
        raw = labels.get(key)

        if raw is None:
            continue

        text = str(raw).strip()

        if not text:
            continue

        rows.append((title, text))

    return rows


def alert_annotation(alert, *keys):
    """Return the first non-empty annotation or label among ``keys``."""

    summary = getattr(alert, "payload_summary", None) or {}

    if isinstance(summary, dict):
        latest = summary.get("latest_payload") or {}

        if isinstance(latest, dict):
            annotations = latest.get("annotations") or {}

            if isinstance(annotations, dict):
                for key in keys:
                    value = str(annotations.get(key) or "").strip()

                    if value:
                        return value

    labels = alert_labels(alert)

    for key in keys:
        value = str(labels.get(key) or "").strip()

        if value:
            return value

    return ""
