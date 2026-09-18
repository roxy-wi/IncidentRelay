"""Normalizer for Cloud.ru Advanced Cloud Eye notifications delivered by SMN."""

from __future__ import annotations

import json
from collections.abc import Mapping

from app.services.integrations.normalizers.common import (
    canonical_label_key,
    clean_string,
    first_non_empty,
    make_dedup_key,
    normalize_label_value,
    stable_labels,
)


CLOUD_RU_ALARM_LEVELS = {
    "1": "critical",
    "2": "high",
    "3": "warning",
    "4": "info",
    "critical": "critical",
    "major": "high",
    "minor": "warning",
    "informational": "info",
}

RESOLVED_STATUSES = {"ok", "normal", "clear", "cleared", "resolved"}


def _message_payload(message):
    if isinstance(message, Mapping):
        return dict(message)
    if isinstance(message, str):
        try:
            decoded = json.loads(message)
        except (TypeError, ValueError):
            return {"message": message}
        if isinstance(decoded, Mapping):
            return dict(decoded)
    return {}


def _dimension_labels(value):
    labels = {}
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
        for item in items:
            if ":" not in item:
                continue
            name, item_value = item.split(":", 1)
            key = canonical_label_key(name)
            if key and clean_string(item_value):
                labels[f"cloud_ru_dimension_{key}"] = clean_string(item_value)
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            key = canonical_label_key(item.get("name"))
            item_value = normalize_label_value(item.get("value"))
            if key and item_value is not None:
                labels[f"cloud_ru_dimension_{key}"] = item_value
    return labels


def normalize_cloud_ru(payload):
    """Normalize a signed Cloud.ru SMN envelope containing a Cloud Eye alarm."""
    envelope = dict(payload or {})
    message = _message_payload(envelope.get("message"))

    labels = _dimension_labels(message.get("dimension") or message.get("dimensions"))

    fixed = {
        "cloud_ru_alarm_id": message.get("alarm_id"),
        "cloud_ru_alarm_name": message.get("alarm_name"),
        "cloud_ru_alarm_status": message.get("alarm_status") or message.get("alarm_state"),
        "cloud_ru_alarm_level": message.get("alarm_level"),
        "cloud_ru_namespace": message.get("namespace"),
        "cloud_ru_metric_name": message.get("metric_name"),
        "cloud_ru_message_type": message.get("message_type"),
        "cloud_ru_enterprise_project_id": message.get("enterprise_project_id") or message.get("enterpriseProjectId"),
        "cloud_ru_region_id": message.get("region_id") or message.get("regionId"),
        "cloud_ru_topic_urn": envelope.get("topic_urn"),
        "cloud_ru_smn_message_id": envelope.get("message_id"),
    }
    for key, value in fixed.items():
        normalized = normalize_label_value(value)
        if normalized is not None:
            labels[key] = normalized

    for key, value in message.items():
        if key in {
            "alarm_id", "alarm_name", "alarm_status", "alarm_state", "alarm_level",
            "namespace", "metric_name", "message_type", "dimension", "dimensions",
            "enterprise_project_id", "enterpriseProjectId", "region_id", "regionId",
        }:
            continue
        label_key = canonical_label_key(key)
        normalized = normalize_label_value(value)
        if label_key and normalized is not None and not isinstance(value, (dict, list)):
            labels.setdefault(f"cloud_ru_{label_key}", normalized)

    alarm_id = clean_string(message.get("alarm_id"))
    alarm_name = clean_string(message.get("alarm_name"))
    alarm_status = clean_string(message.get("alarm_status") or message.get("alarm_state"))
    namespace = clean_string(message.get("namespace"))
    metric_name = clean_string(message.get("metric_name"))

    status = "resolved" if (alarm_status or "").lower() in RESOLVED_STATUSES else "firing"
    severity_key = clean_string(message.get("alarm_level")) or "4"
    severity = CLOUD_RU_ALARM_LEVELS.get(severity_key.lower(), "info")

    subject = clean_string(envelope.get("subject"))
    title = first_non_empty(alarm_name, subject, metric_name, "Cloud.ru Cloud Eye alarm")
    message_text = first_non_empty(
        message.get("alarm_description"),
        message.get("message"),
        subject,
        "",
    )

    external_id = first_non_empty(alarm_id, alarm_name, envelope.get("message_id"))
    dedup_key = alarm_id
    if not dedup_key:
        dedup_key = make_dedup_key(
            "cloud_ru",
            external_id=external_id,
            title=title,
            labels=stable_labels(labels, exclude={"cloud_ru_smn_message_id", "cloud_ru_alarm_status"}),
        )

    team_slug = clean_string(first_non_empty(labels.get("team"), labels.get("oncall_team")))

    return [{
        "source": "cloud_ru",
        "team_slug": team_slug,
        "external_id": external_id,
        "dedup_key": str(dedup_key),
        "title": str(title)[:255],
        "message": str(message_text or ""),
        "severity": severity,
        "labels": labels,
        "payload": envelope,
        "status": status,
    }]
