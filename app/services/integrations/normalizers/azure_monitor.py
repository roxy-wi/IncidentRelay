from __future__ import annotations

from collections.abc import Mapping

from app.services.integrations.normalizers.common import (
    add_event_link_label,
    canonical_label_key,
    clean_string,
    first_event_link,
    first_non_empty,
    make_dedup_key,
    normalize_label_value,
    stable_labels,
)
from app.services.severity import normalize_severity


AZURE_SEVERITY_MAP = {
    "sev0": "critical",
    "sev1": "high",
    "sev2": "medium",
    "sev3": "warning",
    "sev4": "info",
}

RESOLVED_CONDITIONS = {
    "resolved",
    "closed",
    "inactive",
    "ok",
}


def _mapping(value):
    if isinstance(value, Mapping):
        return value
    return {}


def _first_item(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            if clean_string(item):
                return item
        return None

    return value


def _subscription_id_from_resource_id(resource_id):
    resource_id = clean_string(resource_id)
    if not resource_id:
        return None

    parts = [part for part in resource_id.split("/") if part]

    for index, part in enumerate(parts):
        if (
            part.lower() == "subscriptions"
            and index + 1 < len(parts)
        ):
            return parts[index + 1]

    return None


def normalize_azure_monitor_status(value):
    """Map Azure monitorCondition to IncidentRelay firing/resolved."""

    condition = clean_string(value)
    if not condition:
        return "firing"

    if condition.lower() in RESOLVED_CONDITIONS:
        return "resolved"

    return "firing"


def normalize_azure_monitor_severity(value):
    """Map Azure Sev0-Sev4 to IncidentRelay severity."""

    severity = clean_string(value)
    if not severity:
        return "info"

    mapped = AZURE_SEVERITY_MAP.get(severity.lower())
    if mapped:
        return mapped

    normalized = normalize_severity(severity)

    if normalized in {
        "critical",
        "high",
        "medium",
        "warning",
        "low",
        "info",
    }:
        return normalized

    return "info"


def normalize_azure_monitor_custom_properties(value):
    """Expose Azure customProperties as matcher-friendly labels."""

    labels = {}

    if not isinstance(value, Mapping):
        return labels

    for key, item in value.items():
        label_key = canonical_label_key(key)
        if not label_key:
            continue

        label_value = normalize_label_value(item)
        if label_value is not None:
            labels[label_key] = label_value

    return labels


def normalize_azure_monitor(payload):
    """Normalize Azure Monitor Common Alert Schema payload."""

    payload = dict(payload or {})
    data = _mapping(payload.get("data"))
    essentials = _mapping(data.get("essentials"))
    alert_context = _mapping(data.get("alertContext"))
    custom_properties = _mapping(data.get("customProperties"))

    labels = normalize_azure_monitor_custom_properties(
        custom_properties
    )

    alert_id = clean_string(essentials.get("alertId"))
    alert_rule = clean_string(essentials.get("alertRule"))
    alert_rule_id = clean_string(essentials.get("alertRuleId"))
    origin_alert_id = clean_string(essentials.get("originAlertId"))

    monitor_condition = clean_string(
        essentials.get("monitorCondition")
    )
    azure_severity = clean_string(essentials.get("severity"))
    signal_type = clean_string(essentials.get("signalType"))
    monitoring_service = clean_string(
        essentials.get("monitoringService")
    )
    description = clean_string(essentials.get("description"))

    target_resource_group = clean_string(
        essentials.get("targetResourceGroup")
    )
    target_resource_type = clean_string(
        essentials.get("targetResourceType")
    )

    target_id = clean_string(
        _first_item(essentials.get("alertTargetIDs"))
    )
    configuration_item = clean_string(
        _first_item(essentials.get("configurationItems"))
    )

    subscription_id = _subscription_id_from_resource_id(
        target_id
    )

    fixed_labels = {
        "azure_alert_id": alert_id,
        "azure_alert_rule": alert_rule,
        "azure_alert_rule_id": alert_rule_id,
        "azure_origin_alert_id": origin_alert_id,
        "azure_monitor_condition": monitor_condition,
        "azure_severity": azure_severity,
        "azure_signal_type": signal_type,
        "azure_monitoring_service": monitoring_service,
        "azure_target_resource_id": target_id,
        "azure_configuration_item": configuration_item,
        "azure_resource_group": target_resource_group,
        "azure_resource_type": target_resource_type,
        "azure_subscription_id": subscription_id,
    }

    for key, value in fixed_labels.items():
        if value is not None:
            labels[key] = value

    event_link = first_event_link(
        essentials.get("investigationLink"),
        alert_context.get("linkToSearchResultsUI"),
        alert_context.get("linkToSearchResults"),
    )
    add_event_link_label(labels, event_link)

    title = first_non_empty(
        alert_rule,
        description,
        configuration_item,
        "Azure Monitor alert",
    )

    resource_name = first_non_empty(
        configuration_item,
        target_id,
    )

    fallback_message = None
    if signal_type and resource_name:
        fallback_message = (
            f"{signal_type} alert for {resource_name}"
        )

    message = first_non_empty(
        description,
        alert_context.get("description"),
        fallback_message,
        "",
    )

    status = normalize_azure_monitor_status(
        monitor_condition
    )
    severity = normalize_azure_monitor_severity(
        azure_severity
    )

    external_id = first_non_empty(
        alert_id,
        origin_alert_id,
        alert_rule_id,
        target_id,
    )

    dedup_key = first_non_empty(
        alert_id,
        origin_alert_id,
    )

    if not dedup_key:
        dedup_key = make_dedup_key(
            "azure_monitor",
            external_id=external_id,
            title=title,
            labels=stable_labels(
                labels,
                exclude={
                    "event_link",
                    "azure_monitor_condition",
                    "azure_severity",
                },
            ),
        )

    team_slug = clean_string(
        first_non_empty(
            labels.get("team"),
            labels.get("oncall_team"),
        )
    )

    return [{
        "source": "azure_monitor",
        "team_slug": team_slug,
        "external_id": external_id,
        "dedup_key": str(dedup_key),
        "title": str(title)[:255],
        "message": str(message or ""),
        "severity": severity,
        "labels": labels,
        "payload": payload,
        "status": status,
    }]
