from app.services.integrations.normalizers.common import (
    add_event_link_label,
    first_event_link,
    first_non_empty,
    make_dedup_key,
)


RESOLVED_STATUSES = {
    "clear",
    "cleared",
    "closed",
    "info",
    "normal",
    "ok",
    "recover",
    "recovered",
    "resolved",
    "up",
}


def _clean_identifier(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    if value.lower() in {
        "none",
        "null",
        "none none",
        "null null",
    }:
        return None

    return value


def _set_label(labels, key, value):
    value = _clean_identifier(value)

    if value is not None:
        labels.setdefault(key, value)


def normalize_rmon_status(value):
    status = str(value or "").strip().lower()

    if status in RESOLVED_STATUSES:
        return "resolved"

    return "firing"


def normalize_rmon(payload):
    """Normalize an RMON alert payload."""

    labels = dict(payload.get("labels") or {})

    rmon_name = first_non_empty(
        payload.get("rmon_name"),
        labels.get("rmon_name"),
    )

    check_id = first_non_empty(
        payload.get("multi_check_id"),
        payload.get("check_id"),
        labels.get("rmon_check_id"),
    )

    state_id = first_non_empty(
        payload.get("state_id"),
        labels.get("rmon_state_id"),
    )

    check_name = first_non_empty(
        payload.get("check_name"),
        labels.get("check_name"),
    )

    check_type = first_non_empty(
        payload.get("check_type"),
        labels.get("check_type"),
    )

    target = first_non_empty(
        payload.get("target"),
        labels.get("target"),
        labels.get("instance"),
    )

    title = first_non_empty(
        payload.get("title"),
        check_name,
        labels.get("alertname"),
        "RMON alert",
    )

    message = first_non_empty(
        payload.get("message"),
        title,
        "",
    )

    severity = first_non_empty(
        payload.get("severity"),
        labels.get("severity"),
        "warning",
    )

    fingerprint = _clean_identifier(
        payload.get("fingerprint")
    )

    external_id = _clean_identifier(
        first_non_empty(
            payload.get("external_id"),
            check_id,
            fingerprint,
        )
    )

    _set_label(labels, "alertname", check_name or title)
    _set_label(labels, "severity", severity)

    _set_label(labels, "rmon_name", rmon_name)
    _set_label(labels, "rmon_check_id", check_id)
    _set_label(labels, "rmon_state_id", state_id)
    _set_label(labels, "rmon_check_name", check_name)
    _set_label(labels, "rmon_check_type", check_type)

    _set_label(labels, "target", target)
    _set_label(labels, "rmon_agent", payload.get("agent"))
    _set_label(labels, "rmon_region", payload.get("region"))
    _set_label(labels, "rmon_country", payload.get("country"))

    event_link = first_event_link(
        payload.get("event_link"),
        payload.get("runbook_url"),
        labels.get("event_link"),
        labels.get("runbook_url"),
    )

    add_event_link_label(labels, event_link)

    if payload.get("runbook_url"):
        _set_label(
            labels,
            "runbook_url",
            payload.get("runbook_url"),
        )

    dedup_key = fingerprint or make_dedup_key(
        "rmon",
        external_id,
        title,
        labels,
    )

    return [
        {
            "source": "rmon",
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
            "status": normalize_rmon_status(
                payload.get("status")
                or severity
            ),
        }
    ]
