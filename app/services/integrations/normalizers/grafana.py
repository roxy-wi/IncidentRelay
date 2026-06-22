from app.services.integrations.normalizers.common import (
    add_event_link_label,
    first_event_link,
    first_non_empty,
    make_dedup_key,
)


RESOLVED_STATUSES = {
    "ok",
    "normal",
    "closed",
    "clear",
    "cleared",
    "recover",
    "recovered",
    "resolved",
}


def normalize_grafana_status(value):
    """Convert a Grafana alert status to an IncidentRelay status."""
    status = str(value or "").strip().lower()

    if status in RESOLVED_STATUSES:
        return "resolved"

    return "firing"


def _set_label(labels, key, value):
    if value is None:
        return

    value = str(value).strip()
    if value:
        labels.setdefault(key, value)


def _stable_labels(labels, org_id=None):
    stable = {
        str(key): labels[key]
        for key in sorted(labels, key=lambda item: str(item))
    }

    if org_id is not None:
        stable["grafana_org_id"] = str(org_id)

    return stable


def _stored_alert_payload(payload, alert):
    stored_payload = dict(payload)

    # Each IncidentRelay alert stores only its own Grafana alert instance,
    # while retaining the group-level Grafana context.
    stored_payload["alerts"] = [dict(alert)]

    return stored_payload


def normalize_grafana(payload):
    """Normalize a Grafana Alerting webhook payload."""
    result = []

    common_labels = dict(payload.get("commonLabels") or {})
    common_annotations = dict(payload.get("commonAnnotations") or {})

    for item in payload.get("alerts") or []:
        labels = dict(common_labels)
        labels.update(item.get("labels") or {})

        annotations = dict(common_annotations)
        annotations.update(item.get("annotations") or {})

        dashboard_url = item.get("dashboardURL")
        panel_url = item.get("panelURL")
        generator_url = item.get("generatorURL")
        silence_url = item.get("silenceURL")
        grafana_url = payload.get("externalURL")

        event_link = first_event_link(
            dashboard_url,
            panel_url,
            generator_url,
            silence_url,
            grafana_url,
        )

        add_event_link_label(labels, event_link)

        _set_label(labels, "dashboard_url", dashboard_url)
        _set_label(labels, "panel_url", panel_url)
        _set_label(labels, "generator_url", generator_url)
        _set_label(labels, "silence_url", silence_url)
        _set_label(labels, "grafana_url", grafana_url)

        _set_label(labels, "grafana_org_id", payload.get("orgId"))
        _set_label(labels, "grafana_receiver", payload.get("receiver"))
        _set_label(labels, "grafana_group_key", payload.get("groupKey"))
        _set_label(labels, "grafana_state", payload.get("state"))

        title = first_non_empty(
            annotations.get("summary"),
            labels.get("alertname"),
            payload.get("title"),
            "Grafana alert",
        )

        message = first_non_empty(
            annotations.get("description"),
            annotations.get("message"),
            payload.get("message"),
            item.get("valueString"),
            "",
        )

        rule_uid = first_non_empty(
            labels.get("__alert_rule_uid__"),
            labels.get("rule_uid"),
            labels.get("grafana_rule_uid"),
        )

        external_id = first_non_empty(
            item.get("fingerprint"),
            rule_uid,
        )

        dedup_key = (
            item.get("fingerprint")
            or make_dedup_key(
                "grafana",
                external_id,
                title,
                _stable_labels(
                    labels,
                    org_id=payload.get("orgId"),
                ),
            )
        )

        result.append({
            "source": "grafana",
            "team_slug": (
                labels.get("team")
                or labels.get("oncall_team")
                or payload.get("team")
            ),
            "external_id": external_id,
            "dedup_key": dedup_key,
            "title": title,
            "message": message or "",
            "severity": (
                labels.get("severity")
                or labels.get("priority")
                or labels.get("level")
            ),
            "labels": labels,
            "annotations": annotations,
            "payload": _stored_alert_payload(payload, item),
            "status": normalize_grafana_status(
                item.get("status") or payload.get("status")
            ),
        })

    return result
