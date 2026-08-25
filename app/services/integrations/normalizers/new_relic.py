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


RESOLVED_STATES = {
    "close",
    "closed",
    "inactive",
    "ok",
    "recover",
    "recovered",
    "resolved",
}


def _canonical_payload(payload):
    result = {}
    for key, value in (payload or {}).items():
        normalized = canonical_label_key(key)
        if not normalized:
            continue
        if normalized not in result or result[normalized] is None:
            result[normalized] = value
    return result


def _get(data, *names):
    for name in names:
        value = data.get(canonical_label_key(name))
        if value is not None:
            return value
    return None


def _mapping_get(mapping, *names):
    if not isinstance(mapping, Mapping):
        return None

    canonical = {
        canonical_label_key(key): value
        for key, value in mapping.items()
        if canonical_label_key(key)
    }
    return _get(canonical, *names)


def _first_value(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            if item is not None and str(item).strip():
                return item
        return None
    return value


def _nested_first(mapping, *names):
    return _first_value(_mapping_get(mapping, *names))


def normalize_new_relic_status(*values):
    """Map New Relic issue/workflow state to IncidentRelay firing/resolved."""

    for value in values:
        normalized = clean_string(value)
        if not normalized:
            continue

        normalized = normalized.lower().replace("_", " ").replace("-", " ")
        normalized = " ".join(normalized.split())
        if normalized in RESOLVED_STATES:
            return "resolved"

    return "firing"


def normalize_new_relic_severity(priority=None, severity=None):
    """Map New Relic issue priority/severity to IncidentRelay severity."""

    for value in (severity, priority):
        value = clean_string(value)
        if not value:
            continue

        normalized = normalize_severity(value)
        if normalized:
            return normalized

    return "info"


def normalize_new_relic_labels(value):
    """Flatten New Relic labels/rawTag data into matcher-friendly labels."""

    labels = {}

    if value is None:
        return labels

    if isinstance(value, Mapping):
        for key, item in value.items():
            key = clean_string(key)
            if not key:
                continue

            item = _first_value(item)
            item = normalize_label_value(item)
            if item is not None:
                labels[key] = item
        return labels

    if isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, Mapping):
                key = first_non_empty(
                    _mapping_get(item, "key", "name"),
                    _mapping_get(item, "label"),
                )
                label_value = first_non_empty(
                    _mapping_get(item, "value"),
                    _mapping_get(item, "values"),
                )
                if key:
                    labels[str(key)] = normalize_label_value(
                        _first_value(label_value)
                    )
            else:
                text = clean_string(item)
                if not text:
                    continue
                if ":" in text:
                    key, label_value = text.split(":", 1)
                    labels.setdefault(key.strip(), label_value.strip())
                else:
                    labels.setdefault(text, "true")
        return labels

    text = clean_string(value)
    if not text:
        return labels

    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            key, label_value = item.split(":", 1)
            labels.setdefault(key.strip(), label_value.strip())
        else:
            labels.setdefault(item, "true")

    return labels


def normalize_new_relic(payload):
    """Normalize a New Relic Alerts Workflows webhook payload."""

    data = _canonical_payload(payload)
    accumulations = _get(data, "accumulations") or {}
    entities_data = _get(data, "entitiesData", "entities_data") or {}

    entities = _mapping_get(entities_data, "entities") or []
    first_entity = entities[0] if isinstance(entities, list) and entities else {}
    entity_types = _mapping_get(entities_data, "types") or []

    labels = {}
    labels.update(normalize_new_relic_labels(_get(data, "labels", "tags")))
    labels.update(
        normalize_new_relic_labels(
            _mapping_get(accumulations, "rawTag", "raw_tag", "tags")
        )
    )

    issue_id = clean_string(
        first_non_empty(
            _get(data, "issueId", "issue_id"),
            _get(data, "incidentId", "incident_id"),
        )
    )
    condition_name = clean_string(
        first_non_empty(
            _get(data, "conditionName", "condition_name"),
            _nested_first(accumulations, "conditionName", "condition_name"),
        )
    )
    policy_name = clean_string(
        first_non_empty(
            _get(data, "policyName", "policy_name"),
            _nested_first(accumulations, "policyName", "policy_name"),
        )
    )
    entity_guid = clean_string(
        first_non_empty(
            _get(data, "entityGuid", "entity_guid"),
            _mapping_get(first_entity, "id", "guid", "entityGuid"),
        )
    )
    entity_name = clean_string(
        first_non_empty(
            _get(data, "entityName", "entity_name"),
            _mapping_get(first_entity, "name", "entityName"),
            _nested_first(accumulations, "targetName", "target_name"),
        )
    )
    entity_type = clean_string(
        first_non_empty(
            _get(data, "entityType", "entity_type"),
            _first_value(entity_types),
            _mapping_get(first_entity, "type", "entityType"),
        )
    )
    priority = clean_string(_get(data, "priority", "issue_priority"))
    explicit_severity = clean_string(_get(data, "severity"))
    state = clean_string(
        _get(data, "current_state", "state", "issue_state")
    )
    raw_status = clean_string(_get(data, "status", "issue_status"))

    fixed_labels = {
        "new_relic_issue_id": issue_id,
        "new_relic_condition": condition_name,
        "new_relic_policy": policy_name,
        "new_relic_entity_guid": entity_guid,
        "new_relic_entity_name": entity_name,
        "new_relic_entity_type": entity_type,
        "new_relic_priority": priority,
        "new_relic_state": state,
        "new_relic_status": raw_status,
    }
    for key, value in fixed_labels.items():
        if value is not None:
            labels.setdefault(key, value)

    event_link = first_event_link(
        _get(data, "issuePageUrl", "issue_page_url", "issue_url"),
        _get(data, "incident_url", "url", "link"),
    )
    add_event_link_label(labels, event_link)

    title = first_non_empty(
        _get(data, "issueTitle", "issue_title", "title", "details"),
        condition_name,
        entity_name,
        "New Relic alert",
    )
    message = first_non_empty(
        _get(data, "message", "description", "details"),
        condition_name,
        "",
    )

    status = normalize_new_relic_status(
        state,
        raw_status,
        _get(data, "event_type", "eventType"),
        "closed" if _get(data, "issueClosedAt", "issue_closed_at") else None,
    )
    severity = normalize_new_relic_severity(
        priority=priority,
        severity=explicit_severity,
    )

    external_id = first_non_empty(issue_id, entity_guid, condition_name)
    dedup_key = first_non_empty(
        issue_id,
        _get(data, "dedup_key", "fingerprint"),
    )
    if not dedup_key:
        dedup_key = make_dedup_key(
            "new_relic",
            external_id=external_id,
            title=title,
            labels=stable_labels(
                labels,
                exclude={"event_link", "new_relic_state", "new_relic_status"},
            ),
        )

    team_slug = first_non_empty(
        _get(data, "team", "oncall_team"),
        labels.get("team"),
        labels.get("oncall_team"),
    )

    return [{
        "source": "new_relic",
        "team_slug": team_slug,
        "external_id": external_id,
        "dedup_key": str(dedup_key),
        "title": str(title)[:255],
        "message": str(message or ""),
        "severity": severity,
        "labels": labels,
        "payload": dict(payload or {}),
        "status": status,
    }]
