"""Optional webhook mappings accept explicit JSON null as an empty mapping."""

import pytest
from pydantic import ValidationError

from app.api.schemas.integrations import (
    AlertmanagerAlertSchema,
    AlertmanagerWebhookSchema,
    DatadogWebhookSchema,
    GenericWebhookSchema,
    GrafanaAlertSchema,
    GrafanaWebhookSchema,
    LibreNMSWebhookSchema,
    NagiosWebhookSchema,
    NewRelicWebhookSchema,
    RmonWebhookSchema,
    SentryWebhookSchema,
    UptimeKumaWebhookSchema,
    ZabbixWebhookSchema,
)


def test_alertmanager_explicit_null_maps_normalize_to_empty_dicts():
    payload = AlertmanagerWebhookSchema.model_validate(
        {
            "alerts": [
                {
                    "labels": None,
                    "annotations": None,
                }
            ],
            "groupLabels": None,
            "commonLabels": None,
            "commonAnnotations": None,
        }
    )

    assert payload.groupLabels == {}
    assert payload.commonLabels == {}
    assert payload.commonAnnotations == {}
    assert payload.alerts[0].labels == {}
    assert payload.alerts[0].annotations == {}


def test_grafana_explicit_null_maps_normalize_to_empty_dicts():
    payload = GrafanaWebhookSchema.model_validate(
        {
            "alerts": [
                {
                    "labels": None,
                    "annotations": None,
                    "values": None,
                }
            ],
            "groupLabels": None,
            "commonLabels": None,
            "commonAnnotations": None,
        }
    )

    assert payload.groupLabels == {}
    assert payload.commonLabels == {}
    assert payload.commonAnnotations == {}
    assert payload.alerts[0].labels == {}
    assert payload.alerts[0].annotations == {}
    assert payload.alerts[0].values == {}


@pytest.mark.parametrize(
    ("schema", "payload", "field"),
    [
        (ZabbixWebhookSchema, {"title": "zabbix", "labels": None}, "labels"),
        (DatadogWebhookSchema, {"title": "datadog", "labels": None}, "labels"),
        (
            NewRelicWebhookSchema,
            {
                "issue_id": "1",
                "labels": None,
                "accumulations": None,
                "entitiesData": None,
            },
            "labels",
        ),
        (NagiosWebhookSchema, {"host_name": "host", "labels": None}, "labels"),
        (UptimeKumaWebhookSchema, {"msg": "down", "labels": None}, "labels"),
        (GenericWebhookSchema, {"title": "generic", "labels": None}, "labels"),
        (RmonWebhookSchema, {"title": "rmon", "labels": None}, "labels"),
        (SentryWebhookSchema, {"data": None}, "data"),
        (LibreNMSWebhookSchema, {"title": "librenms", "labels": None}, "labels"),
    ],
)
def test_optional_integration_maps_accept_explicit_null(schema, payload, field):
    parsed = schema.model_validate(payload)

    assert getattr(parsed, field) == {}

    if schema is NewRelicWebhookSchema:
        assert parsed.accumulations == {}
        assert parsed.entitiesData == {}


def test_nullable_mapping_still_rejects_non_mapping_values():
    with pytest.raises(ValidationError):
        GrafanaAlertSchema.model_validate({"values": []})

    with pytest.raises(ValidationError):
        AlertmanagerAlertSchema.model_validate({"labels": "not-a-map"})
