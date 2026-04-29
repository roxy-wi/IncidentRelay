import hashlib


def make_hash(value):
    """
    Build a stable hash from a Python value.
    """

    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def make_dedup_key(source, external_id=None, title=None, labels=None):
    """
    Create a stable deduplication key.
    """

    return make_hash({"source": source, "external_id": external_id, "title": title, "labels": labels or {}})


def normalize_alertmanager(payload):
    """
    Normalize Prometheus Alertmanager payload.
    """

    result = []
    for item in payload.get("alerts", []):
        labels = item.get("labels", {})
        annotations = item.get("annotations", {})
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


def normalize_zabbix(payload):
    """
    Normalize Zabbix webhook payload.
    """

    labels = payload.get("labels") or {}
    external_id = payload.get("event_id") or payload.get("trigger_id")
    title = payload.get("title") or payload.get("subject") or "Zabbix alert"
    return [{
        "source": "zabbix",
        "team_slug": payload.get("team") or labels.get("team") or labels.get("oncall_team"),
        "external_id": external_id,
        "dedup_key": payload.get("fingerprint") or make_dedup_key("zabbix", external_id, title, labels),
        "title": title,
        "message": payload.get("message") or "",
        "severity": payload.get("severity"),
        "labels": labels,
        "payload": payload,
        "status": payload.get("status", "firing"),
    }]


def normalize_webhook(payload):
    """
    Normalize a generic webhook payload.
    """

    labels = payload.get("labels") or {}
    title = payload.get("title") or "Webhook alert"
    return [{
        "source": "webhook",
        "team_slug": payload.get("team") or labels.get("team") or labels.get("oncall_team"),
        "external_id": payload.get("external_id"),
        "dedup_key": payload.get("fingerprint") or make_dedup_key("webhook", payload.get("external_id"), title, labels),
        "title": title,
        "message": payload.get("message") or "",
        "severity": payload.get("severity"),
        "labels": labels,
        "payload": payload,
        "status": payload.get("status", "firing"),
    }]
