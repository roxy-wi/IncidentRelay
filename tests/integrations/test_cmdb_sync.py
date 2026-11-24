"""Jira Assets catalog imports, explicit ownership and failure boundaries."""

import copy
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from openapi_schema_validator import OAS30Validator
from openapi_spec_validator import validate
from pydantic import ValidationError

from app.modules.common import utc_now
from app.modules.crypto import encrypt_json
from app.modules.db.models import (
    BusinessService, BusinessServiceComponent, DirectorySyncBinding as Binding,
    DirectorySyncSource as Source, Service, ServiceDependency, Team,
)
from app.services.sync.cmdb.config import CmdbConfig, jira_assets_preset
from app.services.service_catalog import mutations as service_mutations
from app.services.sync.cmdb.fetch import fetch_snapshot
from app.services.sync.directory import client as http, service
from app.services.sync.directory.client import ApiClient
from app.services.sync.directory.config import SyncError
from app.services.sync.directory.management import remove_source
from app.modules.db.transactions import write_transaction
from tests.factories import create_group, create_service, create_team


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


@pytest.mark.parametrize("api_path", [
    "rest/insight/1.0/iql/objects", "/rest/insight/1.0/iql/objects",
    "  rest/insight/1.0/iql/objects  ", "  /rest/insight/1.0/iql/objects  ",
])
def test_catalog_api_path_normalizes_missing_slash(api_path):
    config = CmdbConfig.model_validate({**jira_assets_preset(), "api_path": api_path})
    assert config.api_path == "/rest/insight/1.0/iql/objects"
    assert config.operations["services"].path == config.api_path


@pytest.mark.parametrize("api_path", [
    "", "   ", "https://jira.example.com/rest/insight/1.0/iql/objects",
    "//jira.example.com/rest/insight/1.0/iql/objects", "https:rest/insight",
    "rest/insight?iql=objectType", "/rest/insight#fragment", "rest\\insight",
])
def test_catalog_api_path_rejects_urls_and_non_path_input(api_path):
    with pytest.raises(ValidationError):
        CmdbConfig.model_validate({**jira_assets_preset(), "api_path": api_path})


@pytest.mark.parametrize("updating", [False, True])
def test_save_catalog_normalizes_api_path(client, admin_headers, cmdb_source, updating):
    config = {**cmdb_source.config, "api_path": "rest/insight/1.0/iql/objects"}
    payload = {"name": "Catalog with relative path", "group_id": cmdb_source.group_id, "config": config}
    if updating:
        payload["revision"] = cmdb_source.revision
        response = client.put(f"{URL}/{cmdb_source.id}", headers=admin_headers, json=payload)
    else:
        response = client.post(URL, headers=admin_headers, json=payload)
    assert response.status_code == (200 if updating else 201), response.json
    assert response.json["config"]["api_path"] == "/rest/insight/1.0/iql/objects"
    assert Source.get_by_id(response.json["id"]).config["api_path"] == "/rest/insight/1.0/iql/objects"


@pytest.mark.parametrize("field, value", [
    ("api_path", "https://jira.example.com/rest/insight?token=private-test-token"),
    ("page_size", 0),
    ("services", {"query": ""}),
])
def test_invalid_catalog_only_reports_selected_schema(client, admin_headers, cmdb_source, field, value):
    response = client.post(URL, headers=admin_headers, json={
        "name": "Invalid catalog", "group_id": cmdb_source.group_id,
        "config": {**cmdb_source.config, field: value},
        "headers": {"Authorization": "Bearer private-test-token"},
    })
    assert response.status_code == 400
    expected_field = "config.services.query" if field == "services" else f"config.{field}"
    assert [item["field"] for item in response.json["details"]] == [expected_field]
    assert "private-test-token" not in response.get_data(as_text=True)
    assert Source.select().count() == 1


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


def test_automatic_teams_preview_apply_and_reuse(cmdb_source, upstream, pages, client, admin_headers):
    group = cmdb_source.group
    existing = create_team(group=group, name="  OPERATIONS ")
    create_team(group=create_group(), name="Product team")
    config = {**cmdb_source.config, "create_missing_teams": True, "team_matches": {}}
    payload = {"name": cmdb_source.name, "group_id": group.id, "revision": cmdb_source.revision, "config": config}
    saved = client.put(f"{URL}/{cmdb_source.id}", headers=admin_headers, json=payload)
    assert saved.status_code == 200
    preview = service.run(cmdb_source.id, mode="preview")
    assert preview["preview_token"] and not preview["issues"]
    assert [(item["external_id"], item["action"]) for item in preview["changes"] if item["kind"] == "team"] == [
        ("11", "match"), ("12", "create"),
    ]
    assert not Team.select().where(Team.group == group, Team.name == "Product team").exists()
    assert Source.get_by_id(cmdb_source.id).config["team_matches"] == {}
    # Consume the team ID used by the rolled-back preview.
    create_team(group=group, name="Unrelated team")
    result = service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert result["changes"] == preview["changes"]
    created = Team.get(Team.group == group, Team.name == "Product team")
    assert created.active and BusinessService.get().owner_team_id == created.id
    assert Service.get().team_id == existing.id
    source = Source.get_by_id(cmdb_source.id)
    assert source.config["team_matches"] == {"11": existing.id, "12": created.id}
    assert source.revision == source.approved_revision == saved.json["revision"] + 1
    payload["revision"] = saved.json["revision"]
    assert client.put(f"{URL}/{source.id}", headers=admin_headers, json=payload).status_code == 409

    owner = pages["business_services"]["objectEntries"][0]["attributes"][0]
    owner["objectAttributeValues"] = [ref(12, "Renamed in Jira")]
    assert service.run(source.id)["changes"] == []
    with write_transaction():
        remove_source(Source.get_by_id(source.id), delete_imported=True)
    assert not Team.get_by_id(created.id).deleted and not Team.get_by_id(existing.id).deleted


@pytest.mark.parametrize("conflict", ["ambiguous", "inactive", "foreign_mapping", "missing_name", "duplicate_jira_name"])
def test_automatic_teams_require_explicit_resolution_on_conflict(cmdb_source, upstream, pages, conflict):
    cmdb_source.config.update(create_missing_teams=True, team_matches={})
    if conflict == "ambiguous":
        for name in ("Operations", "operations"):
            create_team(group=cmdb_source.group, name=name)
    elif conflict == "inactive":
        Team.update(name="Operations", active=False).where(Team.id == Team.select().first().id).execute()
    elif conflict == "foreign_mapping":
        foreign = create_team(group=create_group(), name="Operations")
        cmdb_source.config["team_matches"]["11"] = foreign.id
    elif conflict == "missing_name":
        pages["services"]["objectEntries"][0]["attributes"][0]["objectAttributeValues"] = [ref(11, "")]
    else:
        pages["business_services"]["objectEntries"][0]["attributes"][0]["objectAttributeValues"] = [ref(12, "OPERATIONS")]
    cmdb_source.save()
    count = Team.select().count()
    result = service.run(cmdb_source.id, mode="preview")
    assert result["issues"] and result["preview_token"] is None
    assert Team.select().count() == count and not Service.select().exists()


def test_automatic_teams_roll_back_when_plan_changes(cmdb_source, upstream):
    cmdb_source.config.update(create_missing_teams=True, team_matches={})
    cmdb_source.save()
    preview = service.run(cmdb_source.id, mode="preview")
    create_team(group=cmdb_source.group, name="Product team")
    with pytest.raises(SyncError, match="Local data changed"):
        service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert not Team.select().where(Team.name == "Operations").exists()
    assert not Service.select().exists() and not BusinessService.select().exists()
    assert Source.get_by_id(cmdb_source.id).config["team_matches"] == {}


def test_scheduled_team_creation_and_disabling_the_option(cmdb_source, upstream, pages, client, admin_headers):
    cmdb_source.config["create_missing_teams"] = True
    cmdb_source.enabled = True
    cmdb_source.save()
    apply(cmdb_source)
    systems = pages["services"]
    systems["objectEntries"].append(obj(102, "Storage", {1: [ref(13, "Storage team")]}))
    systems["totalFilterCount"] = 2
    Source.update(next_run_at=utc_now() - timedelta(seconds=1)).where(Source.id == cmdb_source.id).execute()
    assert service.process_due_sources() == 1
    source = Source.get_by_id(cmdb_source.id)
    assert source.config["team_matches"]["13"] == Service.get(Service.name == "Storage").team_id
    assert source.approved_revision == source.revision

    payload = {"name": source.name, "group_id": source.group_id, "revision": source.revision,
               "config": {**source.config, "create_missing_teams": False}}
    saved = client.put(f"{URL}/{source.id}", headers=admin_headers, json=payload)
    assert saved.status_code == 200 and not saved.json["approved"]
    assert apply(source)["changes"] == []
    systems["objectEntries"].append(obj(103, "Payments", {1: [ref(14, "Payment team")]}))
    systems["totalFilterCount"] = 3
    preview = service.run(source.id, mode="preview")
    assert preview["issues"] and not preview["preview_token"]
    assert not Team.select().where(Team.name == "Payment team").exists()


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


@pytest.fixture
def dependency_catalog(cmdb_source, pages):
    """Two systems reference a common upstream service, returned last by Jira."""
    systems = pages["services"]
    systems["objectTypeAttributes"].append({"id": 16, "name": "Prod System", "type": 1})
    systems["objectEntries"][0]["attributes"].append(
        {"objectTypeAttributeId": 16, "objectAttributeValues": [ref(103, "Platform"), ref(103, "Platform")]}
    )
    systems["objectEntries"].extend([
        obj(102, "Network", {1: [ref(11, "Operations")], 16: [ref(103, "Platform")]}),
        obj(103, "Platform", {1: [ref(12, "Product team")]}),
    ])
    systems["totalFilterCount"] = 3
    cmdb_source.config["dependency_attribute"] = "Prod System"
    cmdb_source.save()
    return systems


def test_dependency_preview_apply_and_repeat(cmdb_source, upstream, dependency_catalog):
    preview = service.run(cmdb_source.id, mode="preview")
    planned = [c for c in preview["changes"] if c["kind"] == "dependency"]
    assert [(c["external_id"], c["fields"]) for c in planned] == [
        ("101:103", {"service": "101", "depends_on_service": "103"}),
        ("102:103", {"service": "102", "depends_on_service": "103"}),
    ]
    assert not ServiceDependency.select().exists()
    applied = service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert applied["changes"] == preview["changes"]
    assert {(d.service.name, d.depends_on_service.name) for d in ServiceDependency.select()} == {
        ("Compute", "Platform"), ("Network", "Platform"),
    }
    assert BusinessServiceComponent.get().service.name == "Compute"
    assert service.run(cmdb_source.id)["changes"] == []


@pytest.fixture
def filtered_dependency_target(cmdb_source, upstream, dependency_catalog):
    """Import the upstream alone, then scope Jira to its two dependents."""
    systems = dependency_catalog
    dependents, platform = systems["objectEntries"][:-1], systems["objectEntries"][-1]
    systems.update(objectEntries=[platform], totalFilterCount=1)
    apply(cmdb_source)
    systems.update(objectEntries=dependents, totalFilterCount=len(dependents))
    return Service.get(Service.name == "Platform")


def test_dependencies_use_previous_target_by_id(cmdb_source, upstream, filtered_dependency_target):
    target = filtered_dependency_target
    target.name = "Local platform name"
    target.save()
    upstream.clear()
    preview = service.run(cmdb_source.id, mode="preview")
    planned = [change for change in preview["changes"] if change["kind"] == "dependency"]
    assert not preview["issues"] and not preview["warnings"]
    assert [change["external_id"] for change in planned] == ["101:103", "102:103"]
    assert all(change["fields"]["depends_on_service_ir_id"] == target.id for change in planned)
    assert not ServiceDependency.select().exists()
    applied = service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert applied["changes"] == preview["changes"] and len(upstream) == 2
    assert {(d.service.name, d.depends_on_service_id) for d in ServiceDependency.select()} == {
        ("Compute", target.id), ("Network", target.id),
    }
    assert Service.get_by_id(target.id).name == "Local platform name"
    assert service.run(cmdb_source.id)["changes"] == []


@pytest.mark.parametrize("reason", [
    "other_source", "unowned", "wrong_kind", "deleted", "disabled", "moved_service", "moved_team",
    "archived_reference", "archived_object",
])
def test_ineligible_previous_target_is_skipped(cmdb_source, filtered_dependency_target, dependency_catalog, reason):
    target = filtered_dependency_target
    binding = Binding.get(Binding.source == cmdb_source.id, Binding.kind == "service", Binding.external_id == "103")
    if reason == "other_source":
        binding.source = Source.create(name="Other", group=cmdb_source.group_id, created_by=cmdb_source.created_by_id,
                                       config=cmdb_source.config, headers_encrypted=encrypt_json({}))
        binding.save()
    elif reason == "unowned":
        Binding.update(owned=False).where(Binding.id == binding.id).execute()
    elif reason == "wrong_kind":
        Binding.update(kind="business_service").where(Binding.id == binding.id).execute()
    elif reason == "deleted":
        Service.update(deleted=True).where(Service.id == target.id).execute()
    elif reason == "disabled":
        Service.update(enabled=False).where(Service.id == target.id).execute()
    elif reason == "moved_service":
        Service.update(group=create_group()).where(Service.id == target.id).execute()
    elif reason == "moved_team":
        Service.update(team=create_team(create_group())).where(Service.id == target.id).execute()
    elif reason == "archived_reference":
        attrs = dependency_catalog["objectEntries"][0]["attributes"]
        attrs[-1]["objectAttributeValues"][0]["referencedObject"]["archived"] = True
    else:
        dependency_catalog["objectEntries"].append({**obj(103, "Platform", {}), "archived": True})
        dependency_catalog["totalFilterCount"] += 1
    applied = apply(cmdb_source)
    assert any("Dependency 101 -> 103" in warning for warning in applied["warnings"])
    assert not ServiceDependency.select().exists()
    assert Service.get(Service.name == "Compute")


def test_replaced_previous_target_invalidates_preview(cmdb_source, filtered_dependency_target):
    target = filtered_dependency_target
    preview = service.run(cmdb_source.id, mode="preview")
    replacement = create_service(target.team)
    Binding.update(local_id=replacement.id).where(
        Binding.source == cmdb_source.id, Binding.kind == "service", Binding.external_id == "103"
    ).execute()
    with pytest.raises(SyncError, match="Local data changed"):
        service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert not ServiceDependency.select().exists()
    assert not Service.select().where(Service.name == "Compute").exists()


def test_dependency_removal_requires_mapping_and_both_services(cmdb_source, upstream, dependency_catalog):
    systems = dependency_catalog
    apply(cmdb_source)
    network = ServiceDependency.get(ServiceDependency.service == Service.get(Service.name == "Network"))
    platform = systems["objectEntries"].pop()
    systems["totalFilterCount"] = 2
    systems["objectEntries"][1]["attributes"].pop()
    filtered = service.run(cmdb_source.id)
    assert not filtered["warnings"]
    assert filtered["changes"] == [] and not ServiceDependency.get_by_id(network.id).deleted
    systems["objectEntries"].append(platform)
    systems["totalFilterCount"] = 3
    source = Source.get_by_id(cmdb_source.id)
    source.config["dependency_attribute"] = None
    source.save()
    assert apply(source)["changes"] == []
    source = Source.get_by_id(source.id)
    source.config["dependency_attribute"] = "16"
    source.save()
    removed = apply(source)
    assert [(c["external_id"], c["action"]) for c in removed["changes"]] == [("102:103", "remove")]
    assert ServiceDependency.get_by_id(network.id).deleted
    systems["objectEntries"][1]["attributes"].append(
        {"objectTypeAttributeId": 16, "objectAttributeValues": [ref(103, "Platform")]}
    )
    assert service.run(source.id)["changes"][0]["action"] == "create"
    assert not ServiceDependency.get_by_id(network.id).deleted


def test_dependency_manual_links_and_skipped_references(cmdb_source, upstream, dependency_catalog):
    apply(cmdb_source)
    manual = ServiceDependency.get(ServiceDependency.service == Service.get(Service.name == "Compute"))
    Binding.delete().where(Binding.kind == "dependency", Binding.local_id == manual.id).execute()
    manual.dependency_type = "soft"
    manual.save()
    values = dependency_catalog["objectEntries"][0]["attributes"][-1]["objectAttributeValues"]
    values.extend([ref(101, "Compute"), ref(201, "Cloud")])
    result = service.run(cmdb_source.id)
    assert result["changes"] == []
    assert any("cannot depend on itself" in w for w in result["warnings"])
    assert any("Dependency 101 -> 201" in w for w in result["warnings"])
    values.clear()
    assert service.run(cmdb_source.id)["changes"] == []
    assert not ServiceDependency.get_by_id(manual.id).deleted
    assert not Binding.select().where(Binding.kind == "dependency", Binding.local_id == manual.id).exists()
    assert ServiceDependency.get_by_id(manual.id).dependency_type == "soft"


def test_manual_dependency_after_preview_requires_new_plan(cmdb_source, upstream, dependency_catalog):
    refs = dependency_catalog["objectEntries"][0]["attributes"][-1]["objectAttributeValues"]
    refs.clear()
    apply(cmdb_source)
    refs.append(ref(103, "Platform"))
    preview = service.run(cmdb_source.id, mode="preview")
    assert [c["external_id"] for c in preview["changes"]] == ["101:103"]
    compute = Service.get(Service.name == "Compute")
    platform = Service.get(Service.name == "Platform")
    manual = service_mutations.create_service_dependency(compute.id, {"depends_on_service": platform.id})
    with pytest.raises(SyncError, match="Local data changed"):
        service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert apply(cmdb_source)["changes"] == []
    assert not Binding.select().where(Binding.kind == "dependency", Binding.local_id == manual.id).exists()


def test_manual_restoration_after_import_removal_survives(cmdb_source, upstream, dependency_catalog):
    apply(cmdb_source)
    refs = dependency_catalog["objectEntries"][0]["attributes"][-1]["objectAttributeValues"]
    refs.clear()
    assert service.run(cmdb_source.id)["changes"][0]["action"] == "remove"
    compute = Service.get(Service.name == "Compute")
    platform = Service.get(Service.name == "Platform")
    restored = service_mutations.create_service_dependency(compute.id, {"depends_on_service": platform.id})
    assert service.run(cmdb_source.id)["changes"] == []
    assert not ServiceDependency.get_by_id(restored.id).deleted


@pytest.mark.parametrize("attribute", ["Missing reference", "Description"])
def test_invalid_dependency_mapping_preserves_links(cmdb_source, upstream, dependency_catalog, attribute):
    apply(cmdb_source)
    source = Source.get_by_id(cmdb_source.id)
    source.config["dependency_attribute"] = attribute
    source.save()
    result = service.run(source.id, mode="preview")
    assert result["issues"] and not result["preview_token"]
    assert ServiceDependency.select().where(ServiceDependency.deleted == False).count() == 2


def test_dependency_reconnect_and_delete(cmdb_source, upstream, dependency_catalog):
    apply(cmdb_source)
    with write_transaction():
        remove_source(Source.get_by_id(cmdb_source.id), delete_imported=False)
    replacement = Source.create(name="Replacement", group=cmdb_source.group_id, created_by=cmdb_source.created_by_id,
                                config=cmdb_source.config, headers_encrypted=encrypt_json({}))
    result = apply(replacement)
    assert [(c["external_id"], c["action"]) for c in result["changes"] if c["kind"] == "dependency"] == [
        ("101:103", "reconnect"), ("102:103", "reconnect"),
    ]
    assert ServiceDependency.select().count() == 2
    with write_transaction():
        remove_source(Source.get_by_id(replacement.id), delete_imported=True)
    assert not ServiceDependency.select().where(ServiceDependency.deleted == False).exists()


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


@pytest.mark.parametrize("owner_attributes", [{}, {1: []}], ids=["field-absent", "field-empty"])
def test_new_service_without_owner_is_skipped_until_owner_arrives(cmdb_source, upstream, pages, owner_attributes):
    pending = obj(102, "Pending", {**owner_attributes, 5: [ref(201, "Cloud")]})
    pages["services"]["objectEntries"].append(pending)
    pages["services"]["totalFilterCount"] = 2
    business = pages["business_services"]
    business["objectEntries"][0]["attributes"] = []
    business["objectTypeAttributes"] = [attr for attr in business["objectTypeAttributes"] if attr["id"] != 7]

    inspection = service.run(cmdb_source.id, mode="inspect")
    assert not inspection["issues"] and inspection["warnings"]
    preview = service.run(cmdb_source.id, mode="preview")
    assert preview["preview_token"] and not preview["issues"]
    assert any("DEMO-102" in warning and "skipped" in warning for warning in preview["warnings"])
    result = service.run(cmdb_source.id, mode="apply", preview_token=preview["preview_token"])
    assert result["warnings"] == preview["warnings"]
    assert [item.name for item in Service.select()] == ["Compute"]
    assert BusinessService.get().owner_team_id is None
    assert BusinessServiceComponent.select().count() == 1
    assert not Binding.select().where(Binding.external_id == "102").exists()

    pending["attributes"] = obj(102, "Pending", {1: [ref(11, "Operations")], 5: [ref(201, "Cloud")]})["attributes"]
    service.run(cmdb_source.id)
    assert Service.get(Service.name == "Pending").team_id == cmdb_source.config["team_matches"]["11"]
    assert BusinessServiceComponent.select().count() == 2
    assert service.run(cmdb_source.id)["changes"] == []


def test_missing_owners_preserve_imported_teams_and_update_other_fields(cmdb_source, upstream, pages):
    apply(cmdb_source)
    for kind, owner_id in (("services", 1), ("business_services", 7)):
        collection = pages[kind]
        record = collection["objectEntries"][0]
        record["label"] += " renamed"
        record["attributes"] = [attr for attr in record["attributes"] if attr["objectTypeAttributeId"] != owner_id]
        collection["objectTypeAttributes"] = [attr for attr in collection["objectTypeAttributes"] if attr["id"] != owner_id]

    result = apply(cmdb_source)
    assert [change["fields"] for change in result["changes"]] == [{"name": "Cloud renamed"}, {"name": "Compute renamed"}]
    assert Service.get().team_id == cmdb_source.config["team_matches"]["11"]
    assert BusinessService.get().owner_team_id == cmdb_source.config["team_matches"]["12"]
    assert not BusinessServiceComponent.get().deleted
    assert service.run(cmdb_source.id)["changes"] == []


@pytest.mark.parametrize("automatic", [False, True])
def test_archived_owner_references_are_excluded_before_matching(cmdb_source, upstream, pages, automatic):
    cmdb_source.config["create_missing_teams"] = automatic
    cmdb_source.save()
    systems = pages["services"]
    # The same archived team also appears in a partial reference on another object.
    partial = ref(13, "Retired")
    systems["objectEntries"][0]["attributes"][0]["objectAttributeValues"].append(partial)
    systems["objectEntries"].append(obj(102, "Legacy", {1: [partial]}))
    systems["totalFilterCount"] = 2
    archived = {"referencedObject": {"id": 13, "label": "Retired", "archived": True}}
    pages["business_services"]["objectEntries"][0]["attributes"][0]["objectAttributeValues"] = [archived]

    for mode in ("inspect", "preview"):
        result = service.run(cmdb_source.id, mode=mode)
        assert not result["issues"]
        assert [team["id"] for team in result["team_catalog"]] == ["11"]
    applied = service.run(cmdb_source.id, mode="apply", preview_token=result["preview_token"])
    assert any("DEMO-102" in warning for warning in applied["warnings"])
    assert [item.name for item in Service.select()] == ["Compute"]
    assert Service.get().team_id == cmdb_source.config["team_matches"]["11"]
    assert BusinessService.get().owner_team_id is None
    assert not Team.select().where(Team.name == "Retired").exists()
    assert "13" not in Source.get_by_id(cmdb_source.id).config["team_matches"]
    assert service.run(cmdb_source.id)["changes"] == []


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
    """The new catalog components must preserve a valid OpenAPI 3.0 document."""
    from app.api.openapi.spec import build_openapi_spec

    spec = build_openapi_spec()
    validate(spec)
    schemas = spec["components"]["schemas"]
    assert "DirectorySyncCmdbConfig" in schemas
    assert URL + "/{source_id}/inspect" in spec["paths"]


@pytest.mark.parametrize("source_type, valid", [
    ("jira_assets", True), ("directory", False), ("unknown", False), (None, False), (True, False),
])
def test_catalog_source_type_openapi_matches_runtime(source_type, valid):
    """Published source-type constraints must reject the same values as the API."""
    from app.api.openapi.endpoints.directory_sync import components

    schema = components()["DirectorySyncCmdbConfig"]["properties"]["source_type"]
    assert OAS30Validator(schema).is_valid(source_type) is valid
    config = {**jira_assets_preset(), "source_type": source_type}
    if valid:
        CmdbConfig.model_validate(config)
    else:
        with pytest.raises(ValidationError):
            CmdbConfig.model_validate(config)


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
