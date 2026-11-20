"""Jira Assets catalog imports, explicit ownership and failure boundaries."""

import copy
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from app.modules.common import utc_now
from app.modules.crypto import encrypt_json
from app.modules.db.models import (
    BusinessService, BusinessServiceComponent, DirectorySyncBinding as Binding,
    DirectorySyncSource as Source, Service, Team,
)
from app.services.sync.cmdb.config import CmdbConfig, jira_assets_preset
from app.services.sync.cmdb.fetch import fetch_snapshot
from app.services.sync.directory import client as http, service
from app.services.sync.directory.client import ApiClient
from app.services.sync.directory.config import SyncError
from app.services.sync.directory.management import remove_source
from app.modules.db.transactions import write_transaction
from tests.factories import create_group, create_team


URL = "/api/admin/directory-sync"


def ref(key, name):
    return {"referencedObject": {"id": key, "label": name}}


def page(record, definitions):
    return {"objectEntries": [record], "objectTypeAttributes": [
        {"id": key, "name": name, "type": kind} for key, name, kind in definitions
    ], "totalFilterCount": 1, "pageNumber": 1}


def obj(key, name, attributes):
    return {"id": key, "label": name, "objectKey": f"DEMO-{key}", "attributes": [
        {"objectTypeAttributeId": attr, "objectAttributeValues": values} for attr, values in attributes.items()
    ]}


@pytest.fixture
def pages():
    """Synthetic contract based on Assets, containing no user-provided CMDB data."""
    return {
        "services": page(obj(101, "Compute", {
            1: [ref(11, "Operations")], 2: [{"value": "A compute system"}], 3: [ref(20, "Prod")],
            4: [ref(21, "Business Critical")], 5: [ref(201, "Cloud")],
            6: [{"status": {"id": 22, "name": "Live"}}],
        }), [(1, "SRE Support Team", 1), (2, "Description", 0), (3, "Environment", 1),
             (4, "Criticality", 1), (5, "Product", 1), (6, "Environment Status", 7)]),
        "business_services": page(obj(201, "Cloud", {
            7: [ref(12, "Product team")], 8: [{"value": "Cloud platform"}],
            9: [{"status": {"id": 23, "name": "PRODUCT_STATUS_ACTIVE"}}],
        }), [(7, "Product Support Team", 1), (8, "Long Description", 0), (9, "Status", 7),
             (13, "Short Description", 0)]),
    }


@pytest.fixture
def cmdb_source(admin_user):
    group = create_group()
    operations = create_team(group=group, name="Existing operations")
    product = create_team(group=group, name="Existing product")
    config = jira_assets_preset()
    config["team_matches"] = {"11": operations.id, "12": product.id}
    return Source.create(name="Jira catalog", group=group, created_by=admin_user, config=config,
                         headers_encrypted=encrypt_json({"Authorization": "Bearer secret-test"}))


@pytest.fixture
def upstream(monkeypatch, pages):
    requests = []

    def request(url, **kwargs):
        params = parse_qs(urlsplit(url).query)
        requests.append((params, kwargs))
        query = params.get("qlQuery", params.get("iql"))[0]
        kind = "business_services" if "Product" in query or "Application" in query else "services"
        return 200, {}, json.dumps(pages[kind]).encode()

    monkeypatch.setattr(http, "_request_once", request)
    return requests


def apply(source):
    preview = service.run(source.id, mode="preview")
    assert not preview["issues"], preview
    assert preview["preview_token"]
    return service.run(source.id, mode="apply", preview_token=preview["preview_token"])


def test_inspect_preview_apply_and_repeat_preserve_identity(cmdb_source, upstream, pages):
    inspected = service.run(cmdb_source.id, mode="inspect")
    assert inspected["attributes"]["services"]
    assert {team["id"] for team in inspected["team_catalog"]} == {"11", "12"}
    assert not inspected["preview_token"]
    assert not Service.select().exists()
    preview = service.run(cmdb_source.id, mode="preview")
    assert not Service.select().exists()
    assert not BusinessService.select().exists()
    assert not Binding.select().exists()
    service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    technical, business, component = Service.get(), BusinessService.get(), BusinessServiceComponent.get()
    assert technical.team_id == cmdb_source.config["team_matches"]["11"]
    assert business.owner_team_id == cmdb_source.config["team_matches"]["12"]
    assert component.service_id == technical.id and component.business_service_id == business.id
    assert technical.environment == "production" and technical.criticality == "critical"
    assert technical.metadata["jira_cmdb"]["status"] == "Live"
    assert business.metadata["jira_cmdb"]["status"] == "PRODUCT_STATUS_ACTIVE"
    assert not business.public
    assert Team.select().count() == 2
    assert service.run(cmdb_source.id)["changes"] == []
    pages["services"]["objectEntries"][0]["label"] = "Renamed compute"
    service.run(cmdb_source.id)
    assert Service.get().id == technical.id and Service.get().slug == technical.slug
    assert Service.get().name == "Renamed compute"
    assert all(call[1]["method"] == "GET" for call in upstream)


def test_arbitrary_queries_fields_and_reverse_relationship(cmdb_source, upstream, pages):
    config = cmdb_source.config
    config["services"].update(query='objectType = "Machine" AND objectSchemaId = 17 AND "Name" LIKE "{env}"', owner_team_attribute="1")
    config["business_services"].update(query='objectType = "Application"', owner_team_attribute="7")
    config.update(relationship_side="business_services", relationship_attribute="Systems", query_parameter="iql",
                  api_path="/rest/insight/1.0/iql/objects")
    cmdb_source.save()
    pages["business_services"]["objectTypeAttributes"].append({"id": 10, "name": "Systems", "type": 1})
    pages["business_services"]["objectEntries"][0]["attributes"].append({"objectTypeAttributeId": 10, "objectAttributeValues": [ref(101, "Compute")]})
    apply(cmdb_source)
    assert BusinessServiceComponent.select().count() == 1
    assert upstream[0][0]["iql"] == [config["services"]["query"]]
    assert upstream[0][0]["includeTypeAttributes"] == ["true"]


@pytest.mark.parametrize("mapping", [{}, {"11": -1}, {"11": 999999, "12": 999999}])
def test_bad_team_matches_never_create_teams_or_catalog(cmdb_source, upstream, mapping):
    cmdb_source.config["team_matches"] = mapping
    cmdb_source.save()
    if any(value < 1 for value in mapping.values()):
        with pytest.raises(SyncError):
            service.run(cmdb_source.id, mode="preview")
    else:
        preview = service.run(cmdb_source.id, mode="preview")
        assert preview["issues"] and preview["preview_token"] is None
    assert Team.select().count() == 2
    assert not Service.select().exists()


def test_foreign_team_rejected_on_save_and_rechecked_on_apply(cmdb_source, upstream, client, admin_headers):
    foreign = create_team(group=create_group())
    config = copy.deepcopy(cmdb_source.config)
    config["team_matches"]["11"] = foreign.id
    response = client.put(f"{URL}/{cmdb_source.id}", headers=admin_headers, json={
        "name": cmdb_source.name, "group_id": cmdb_source.group_id, "revision": 1, "config": config,
    })
    assert response.status_code == 409
    preview = service.run(cmdb_source.id, mode="preview")
    Team.update(group=foreign.group_id).where(Team.id == cmdb_source.config["team_matches"]["11"]).execute()
    with pytest.raises(SyncError, match="mappings need attention"):
        service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert not Service.select().exists()


def test_failed_or_incomplete_fetch_preserves_catalog_and_retries_at_interval(cmdb_source, upstream, pages):
    apply(cmdb_source)
    pages["business_services"]["totalFilterCount"] = 2
    with pytest.raises(SyncError, match="pagination"):
        service.run(cmdb_source.id)
    assert Service.select().where(Service.deleted == False).count() == 1
    assert BusinessServiceComponent.get().deleted is False
    refreshed = Source.get_by_id(cmdb_source.id)
    assert refreshed.last_error and refreshed.lease is None
    assert refreshed.next_run_at > utc_now() + timedelta(seconds=3500)


def test_pagination_uses_total_not_requested_page_size(cmdb_source, pages):
    client = ApiClient(CmdbConfig.model_validate(cmdb_source.config), {})
    calls = []

    def request(kind, context, params):
        calls.append((kind, params["page"]))
        response = copy.deepcopy(pages[kind])
        if kind == "services":
            response.update(totalFilterCount=2, pageNumber=params["page"])
            response["objectEntries"][0]["id"] += params["page"] - 1
        return response

    client.request = request
    snapshot = fetch_snapshot(client)
    assert len(snapshot["services"]) == 2
    assert calls == [("services", 1), ("services", 2), ("business_services", 1)]


def test_changed_local_data_invalidates_apply(cmdb_source, upstream):
    apply(cmdb_source)
    preview = service.run(cmdb_source.id, mode="preview")
    Service.update(name="Local edit").execute()
    with pytest.raises(SyncError, match="Local data changed"):
        service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert Service.get().name == "Local edit"


def test_local_metadata_status_and_manual_components_survive(cmdb_source, upstream, pages):
    apply(cmdb_source)
    technical = Service.get()
    Service.update(status="degraded", metadata={**technical.metadata, "custom": "keep"}).execute()
    Binding.delete().where(Binding.kind == "component").execute()
    pages["services"]["objectEntries"][0]["attributes"] = [
        attr for attr in pages["services"]["objectEntries"][0]["attributes"] if attr["objectTypeAttributeId"] != 5
    ]
    service.run(cmdb_source.id)
    assert Service.get().status == "degraded" and Service.get().metadata["custom"] == "keep"
    assert BusinessServiceComponent.get().deleted is False


def test_owned_links_removed_only_when_both_objects_loaded(cmdb_source, upstream, pages):
    apply(cmdb_source)
    pages["business_services"].update(objectEntries=[], totalFilterCount=0)
    result = service.run(cmdb_source.id)
    assert result["warnings"]
    assert BusinessServiceComponent.get().deleted is False
    assert BusinessService.get().deleted is False


def test_retained_source_reconnect_and_delete_never_remove_teams(cmdb_source, upstream):
    apply(cmdb_source)
    identity = Service.get().id
    with write_transaction():
        remove_source(Source.get_by_id(cmdb_source.id), delete_imported=False)
    new = Source.create(name="Replacement", group=cmdb_source.group_id, created_by=cmdb_source.created_by_id,
                        config=cmdb_source.config, headers_encrypted=encrypt_json({}))
    apply(new)
    assert Service.select().count() == 1 and Service.get().id == identity
    with write_transaction():
        remove_source(Source.get_by_id(new.id), delete_imported=True)
    assert Service.get().deleted and BusinessService.get().deleted
    assert Team.select().where(Team.deleted == False).count() == 2


def test_queue_inspect_and_schedule_fences(client, admin_headers, cmdb_source, upstream):
    response = client.post(f"{URL}/{cmdb_source.id}/inspect", headers=admin_headers, json={"revision": 1})
    assert response.status_code == 202
    assert service.process_due_sources() == 0
    inspected = client.get(f"{URL}/{cmdb_source.id}", headers=admin_headers).json
    assert inspected["pending_mode"] is None and inspected["preview_result"]["attributes"]
    assert inspected["source_type"] == "jira_assets" and "secret-test" not in json.dumps(inspected)
    assert inspected["next_current_at"] is None
    apply(cmdb_source)
    before = Source.get_by_id(cmdb_source.id)
    config = copy.deepcopy(before.config)
    config["interval_seconds"] = 7200
    saved = client.put(f"{URL}/{cmdb_source.id}", headers=admin_headers, json={
        "name": before.name, "group_id": before.group_id, "config": config, "revision": before.revision, "enabled": True,
    })
    assert saved.status_code == 200, saved.json
    assert saved.json["approved"] and saved.json["enabled"]
    assert Source.get_by_id(before.id).next_run_at > utc_now() + timedelta(seconds=7100)
    config["services"]["query"] = 'objectType = "Machine"'
    saved = client.put(f"{URL}/{before.id}", headers=admin_headers, json={
        "name": before.name, "group_id": before.group_id, "config": config, "revision": saved.json["revision"], "enabled": True,
    })
    assert saved.status_code == 200 and not saved.json["approved"]
    assert service.process_due_sources() == 0


def test_invalid_relationship_field_does_not_remove_links(cmdb_source, upstream):
    apply(cmdb_source)
    cmdb_source = Source.get_by_id(cmdb_source.id)
    cmdb_source.config["relationship_attribute"] = "Misspelled field"
    cmdb_source.save()
    preview = service.run(cmdb_source.id, mode="preview")
    assert preview["issues"] and not preview["preview_token"]
    assert BusinessServiceComponent.get().deleted is False


def test_removed_reference_only_removes_owned_link(cmdb_source, upstream, pages):
    apply(cmdb_source)
    attrs = pages["services"]["objectEntries"][0]["attributes"]
    next(attr for attr in attrs if attr["objectTypeAttributeId"] == 5)["objectAttributeValues"] = []
    preview = service.run(cmdb_source.id, mode="preview")
    assert preview["changes"] == [{"kind": "component", "external_id": "101:201", "action": "remove", "fields": {}}]
    assert BusinessServiceComponent.get().deleted is False
    service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert BusinessServiceComponent.get().deleted is True
    assert not Service.get().deleted and not BusinessService.get().deleted


def test_owner_field_change_updates_existing_service_team(cmdb_source, upstream, pages):
    apply(cmdb_source)
    before = Service.get()
    pages["services"]["objectTypeAttributes"].append({"id": 14, "name": "Operations Owner", "type": 1})
    pages["services"]["objectEntries"][0]["attributes"].append({"objectTypeAttributeId": 14, "objectAttributeValues": [ref(12, "Product team")]})
    cmdb_source = Source.get_by_id(cmdb_source.id)
    cmdb_source.config["services"]["owner_team_attribute"] = "14"
    cmdb_source.save()
    apply(cmdb_source)
    assert Service.get().id == before.id
    assert Service.get().team_id == cmdb_source.config["team_matches"]["12"]


def test_second_active_source_cannot_duplicate_import(cmdb_source, upstream):
    apply(cmdb_source)
    duplicate = Source.create(name="Duplicate", group=cmdb_source.group_id, config=cmdb_source.config,
                              created_by=cmdb_source.created_by_id, headers_encrypted=encrypt_json({}))
    with pytest.raises(SyncError, match="already managed"):
        service.run(duplicate.id, mode="preview")
    assert Service.select().count() == 1


def test_unknown_enums_and_multiple_owner_teams_block_preview(cmdb_source, upstream, pages):
    attrs = pages["services"]["objectEntries"][0]["attributes"]
    next(attr for attr in attrs if attr["objectTypeAttributeId"] == 3)["objectAttributeValues"] = [ref(50, "Custom environment")]
    next(attr for attr in attrs if attr["objectTypeAttributeId"] == 1)["objectAttributeValues"].append(ref(12, "Product team"))
    preview = service.run(cmdb_source.id, mode="preview")
    assert len(preview["issues"]) == 2 and not preview["preview_token"]
    assert "Custom environment" in " ".join(preview["issues"])
    assert not Service.select().exists()


def test_catalog_openapi_schema():
    from app.api.openapi.endpoints.directory_sync import components, paths
    schemas = components()
    assert "DirectorySyncCmdbConfig" in schemas
    assert schemas["DirectorySyncCmdbConfig"]["properties"]["source_type"]["const"] == "jira_assets"
    assert URL + "/{source_id}/inspect" in paths()


def test_pause_source_after_team_becomes_inactive(cmdb_source, upstream, client, admin_headers):
    apply(cmdb_source)
    source = Source.get_by_id(cmdb_source.id)
    Team.update(active=False).where(Team.id == source.config["team_matches"]["11"]).execute()
    response = client.put(f"{URL}/{source.id}", headers=admin_headers, json={
        "name": source.name, "group_id": source.group_id, "config": source.config, "revision": source.revision, "enabled": False,
    })
    assert response.status_code == 200 and not response.json["enabled"]


def test_discovery_can_repair_invalid_field_mappings(cmdb_source, upstream):
    cmdb_source.config["services"].update(owner_team_attribute="Description", name_attribute="No such field")
    cmdb_source.save()
    result = service.run(cmdb_source.id, mode="inspect")
    assert result["issues"] and result["attributes"]["services"]
    assert result["services"] == 1
    assert not Service.select().exists()


@pytest.mark.parametrize("fault", ["http", "invalid_json", "missing_total", "repeat", "max_pages"])
def test_failed_discovery_releases_queue_and_logs(cmdb_source, upstream, pages, monkeypatch, fault, caplog):
    if fault == "http":
        monkeypatch.setattr(http, "_request_once", lambda *args, **kwargs: (401, {}, b"private-response secret-test"))
    elif fault == "invalid_json":
        monkeypatch.setattr(http, "_request_once", lambda *args, **kwargs: (200, {}, b"private-response secret-test"))
    elif fault == "missing_total":
        del pages["services"]["totalFilterCount"]
    else:
        pages["services"]["totalFilterCount"] = 2
        if fault == "max_pages":
            cmdb_source.config["max_pages"] = 1
    cmdb_source.pending_mode = "inspect"
    cmdb_source.save()
    service.process_due_sources()
    source = Source.get_by_id(cmdb_source.id)
    assert source.pending_mode is None and source.lease is None and source.last_error
    assert "Directory synchronization failed" in caplog.text
    assert "private-response" not in caplog.text and "secret-test" not in caplog.text
    assert not Service.select().exists()
