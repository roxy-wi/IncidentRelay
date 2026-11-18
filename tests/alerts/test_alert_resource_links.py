"""Resource links must also work for alerts ingested before the UI supported them."""

import copy
from types import SimpleNamespace

import pytest

from app.api.openapi.endpoints.alerts import alert_child_schema, alert_group_schema
from app.modules.db import alerts_repo
from app.modules.db.models import AlertGroup
from app.services.integrations.normalizers.alertmanager import normalize_alertmanager
from app.services.links import build_alert_resource_links
from tests.factories import create_alert, create_group, create_route, create_team


@pytest.fixture
def stored_alert_with_links(db):
    """Store the same shape as an Alertmanager alert and the UX payload summary."""
    route = create_route(create_team(create_group()), source="alertmanager")
    raw = {
        "annotations": {
            "dashboard_url": "https://grafana.example.test/d/service-controller?var-interval=$__auto&orgId=1",
            "runbook_url": "https://wiki.example.test/x/L7BULg",
            "description": "Available addresses in pool public less than 3%",
            "summary": "Address pool public less than 3%",
        },
        "generatorURL": "http://10.254.0.45:8880/vmalert/alert?group_id=1775&alert_id=6583",
        "labels": {"alertname": "AddressAvailability", "severity": "critical"},
        "fingerprint": "1c183a9861603ea7",
        "startsAt": "2026-11-18T03:01:57.735936556+03:00",
        "endsAt": "2026-11-18T03:14:57.736110528+03:00",
        "status": "resolved",
    }
    normalized = normalize_alertmanager({"alerts": [raw]})[0]
    alert = create_alert(route)
    for key, value in normalized.items():
        if key != "team_slug":
            setattr(alert, key, value)
    group = AlertGroup.create(
        team=route.team, route=route, source=alert.source,
        group_key=alert.group_key, group_key_hash="resource-links",
        title=alert.title,
    )
    alert.group = group
    alert.save()
    group = alerts_repo.recalculate_alert_group(group)
    return alert, group


def test_alert_details_api_exposes_links_from_existing_annotations(
    client, admin_headers, stored_alert_with_links,
):
    alert, group = stored_alert_with_links
    original_payload = copy.deepcopy(group.payload_summary)
    assert "dashboard_url" not in alert.labels
    assert "runbook_url" not in alert.labels
    response = client.get(f"/api/alert-groups/{group.id}", headers=admin_headers)

    assert response.status_code == 200
    result = response.get_json()
    expected = [
        {"kind": "source", "url": alert.payload["generatorURL"]},
        {"kind": "dashboard", "url": alert.payload["annotations"]["dashboard_url"]},
        {"kind": "runbook", "url": alert.payload["annotations"]["runbook_url"]},
    ]
    assert result["resource_links"] == expected
    assert result["alerts"][0]["resource_links"] == expected
    assert AlertGroup.get_by_id(group.id).payload_summary == original_payload


def test_resource_links_prefer_labels_and_do_not_duplicate_source():
    alert = SimpleNamespace(
        labels={"dashboard_url": "https://example.test/override", "event_link": "https://example.test/override"},
        payload={"annotations": {"dashboard_url": "https://example.test/original"}},
    )
    assert build_alert_resource_links(alert) == [
        {"kind": "dashboard", "url": "https://example.test/override"},
    ]


def test_resource_links_read_grafana_instance_and_common_annotations():
    alert = SimpleNamespace(payload={
        "commonAnnotations": {"runbook_url": "https://example.test/runbook"},
        "alerts": [{
            "dashboardURL": "https://example.test/dashboard",
            "panelURL": "https://example.test/dashboard?viewPanel=1",
        }],
    })
    assert [item["kind"] for item in build_alert_resource_links(alert)] == [
        "dashboard", "panel", "runbook",
    ]


@pytest.mark.parametrize("value", ["javascript:alert(1)", "data:text/html,test", "/relative", "https://[broken", None, {}, []])
def test_resource_links_ignore_invalid_urls_and_keep_valid_fallback(value):
    alert = SimpleNamespace(
        labels={"dashboard_url": value, "runbook_url": value, "event_link": value},
        payload={"annotations": {"runbook_url": "https://example.test/runbook"}},
    )
    assert build_alert_resource_links(alert) == [
        {"kind": "runbook", "url": "https://example.test/runbook"},
    ]


@pytest.mark.parametrize("payload", [None, [], "invalid", {"annotations": []}, {"alerts": [None]}, {"latest_payload": []}])
def test_resource_links_tolerate_missing_or_malformed_legacy_payload(payload):
    assert build_alert_resource_links(SimpleNamespace(payload_summary=payload)) == []


def test_resource_links_preserve_legacy_source_only_alerts():
    alert = SimpleNamespace(labels={"event_link": "https://example.test/event"})
    assert build_alert_resource_links(alert) == [
        {"kind": "source", "url": "https://example.test/event"},
    ]


def test_alert_openapi_describes_typed_resource_links():
    for schema in (alert_child_schema(), alert_group_schema()):
        links = schema["properties"]["resource_links"]
        assert links["items"]["required"] == ["kind", "url"]
        assert links["items"]["properties"]["kind"]["enum"] == [
            "source", "dashboard", "panel", "runbook",
        ]
