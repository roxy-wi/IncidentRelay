"""Native GitLab intake reuses machine authority, atomic writes and projection."""

from importlib import import_module

import pytest
from peewee import OperationalError, SqliteDatabase

from app.api.schemas.change_integrations import SourceUpdate
from app.modules.db.models import (
    Change,
    ChangeEvent,
    ChangeJob,
    ChangeSource,
    SystemSettings,
)
from app.services.change_intelligence import administration as admin, ingestion
from app.settings import Config
from tests.factories import create_group, create_service, create_team
from tests.integrations.test_change_integrations import (
    credential,
    grant,
    revision,
    setup_identity,
)

__all__ = ["setup_identity"]


@pytest.fixture
def gitlab(setup_identity):
    integration, source, service, actor = setup_identity
    SystemSettings.update(change_intake_enabled=True).execute()
    permission = grant(setup_identity)
    source = admin.update_source(
        integration.id,
        source.id,
        SourceUpdate(
            expected_revision=revision(integration),
            gitlab_mappings=[
                {
                    "project_id": 42,
                    "environment": "production",
                    "service_ids": [service.id],
                }
            ],
        ),
        actor_id=actor.id,
    )
    token, raw = credential(setup_identity)
    return setup_identity, source, permission, token, raw


def body(**overrides):
    data = {
        "object_kind": "deployment",
        "project": {"id": 42, "path_with_namespace": "platform/api"},
        "deployment_id": 100,
        "status": "success",
        "environment": "production",
        "status_changed_at": "2026-01-01T12:00:00.000+02:00",
        "deployable_url": "https://gitlab.example.com/platform/api/-/jobs/123",
        "short_sha": "abcdef12",
        "user": {"name": "Engineer", "email": "ignored@example.com"},
    }
    data.update(overrides)
    return data


def send(client, gitlab, payload=None, headers=None, source_id=None):
    return client.post(
        f"/api/change-events/gitlab/{source_id or gitlab[1].id}",
        json=body() if payload is None else payload,
        headers=headers
        if headers is not None
        else {
            "X-Gitlab-Token": gitlab[4],
            "X-Gitlab-Event": "Deployment Hook",
        },
    )


def test_native_lifecycle_out_of_order_and_redelivery(client, gitlab):
    completed = send(client, gitlab)
    assert completed.status_code == 201, completed.json
    assert completed.json["status"] == "succeeded"
    assert completed.json["references"] == {"total": 1, "resolved": 1, "pending": 0}
    started = send(
        client, gitlab, body(status="running", status_changed_at="2026-01-01T09:00:00Z")
    )
    assert started.status_code == 201
    assert started.json["change_uid"] == completed.json["change_uid"]
    assert started.json["status"] == "succeeded"
    change = Change.get()
    assert change.owner_team_id == gitlab[1].owner_team_id
    assert change.started_at.hour == 9 and change.completed_at.hour == 10
    jobs = [(job.id, job.requested_generation) for job in ChangeJob.select()]
    retry = send(
        client,
        gitlab,
        body(status_changed_at="2026-01-01T10:00:00Z"),
        headers={
            "X-Gitlab-Token": gitlab[4],
            "X-Gitlab-Event": "Deployment Hook",
            "X-Gitlab-Event-UUID": "different-delivery-id",
        },
    )
    assert retry.status_code == 200
    assert retry.json["event_uid"] == completed.json["event_uid"]
    assert ChangeEvent.select().count() == 2
    assert [(job.id, job.requested_generation) for job in ChangeJob.select()] == jobs
    event = ChangeEvent.get(ChangeEvent.event_type == "change.succeeded")
    assert event.actor_label == "Engineer"
    assert "email" not in str(event.request_snapshot)
    assert "ignored@example.com" not in str(event.request_snapshot)
    assert send(client, gitlab, body(short_sha="changed")).status_code == 409


@pytest.mark.parametrize(
    "state,expected",
    [
        ("running", "running"),
        ("failed", "failed"),
        ("canceled", "cancelled"),
        ("blocked", "unknown"),
        ("approved", "unknown"),
        ("rejected", "unknown"),
    ],
)
def test_status_translation(client, gitlab, state, expected):
    result = send(client, gitlab, body(status=state, deployable_url=None))
    assert result.status_code == 201, result.json
    assert result.json["status"] == expected


@pytest.mark.parametrize("required", [True, False])
def test_native_header_requires_machine_token_even_with_jwt(
    client, gitlab, admin_headers, monkeypatch, required
):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", required)
    for headers in (
        {},
        admin_headers,
        {"X-Gitlab-Token": "wrong"},
        {
            "X-Gitlab-Token": gitlab[4],
            "Authorization": "Bearer wrong",
        },
        {
            "X-Gitlab-Token": "tökén",
            "Authorization": "Bearer " + gitlab[4],
        },
    ):
        result = send(
            client, gitlab, headers={**headers, "X-Gitlab-Event": "Deployment Hook"}
        )
        assert result.status_code == 401
    result = send(
        client,
        gitlab,
        headers={
            "Authorization": "Bearer " + gitlab[4],
            "X-Gitlab-Event": "Deployment Hook",
        },
    )
    assert result.status_code == 201
    gitlab[3].active = False
    gitlab[3].save()
    assert send(client, gitlab).status_code == 401


def test_disabled_source_token_scope_and_intake(client, gitlab):
    SystemSettings.update(change_intake_enabled=False).execute()
    assert send(client, gitlab).status_code == 404
    SystemSettings.update(change_intake_enabled=True).execute()
    other = admin.create_integration(
        "Other", actor_id=gitlab[0][3].id, owner_team_id=gitlab[1].owner_team_id
    )
    foreign_source = ChangeSource.get(ChangeSource.integration == other.id)
    assert send(client, gitlab, source_id=foreign_source.id).status_code == 403
    ChangeSource.update(active=False).where(ChangeSource.id == gitlab[1].id).execute()
    assert send(client, gitlab).status_code == 403
    assert ChangeEvent.select().count() == 0


def test_mapping_matches_both_project_and_environment(client, gitlab):
    for payload in (body(environment="staging"), body(project={"id": 43})):
        result = send(client, gitlab, payload)
        assert result.status_code == 200
        assert result.json == {"status": "ignored", "reason": "no_matching_mapping"}
    assert Change.select().count() == 0
    # Native sender fields never override the configured team or service list.
    result = send(
        client, gitlab, body(owner_team_id=999999, changed_service_ids=[999999])
    )
    assert result.status_code == 201
    assert Change.get().owner_team_id == gitlab[1].owner_team_id


def test_replay_after_mapping_change_and_grant_revocation(client, gitlab):
    first = send(client, gitlab)
    assert first.status_code == 201
    source = gitlab[1]
    source.gitlab_mappings = []
    source.save()
    assert send(client, gitlab).json == first.json
    assert send(client, gitlab, body(deployment_id=101)).json["status"] == "ignored"
    source.gitlab_mappings = [
        {
            "project_id": 42,
            "environment": "production",
            "service_ids": [gitlab[0][2].id],
        }
    ]
    source.save()
    gitlab[2].active = False
    gitlab[2].save()
    assert send(client, gitlab, body(deployment_id=101)).status_code == 403
    assert Change.select().count() == 1
    assert ChangeEvent.select().count() == 1


def test_multiple_services_and_projects(client, gitlab):
    identity, source, *_ = gitlab
    other_service = create_service(create_team(create_group()))
    grant(identity, team=other_service.team_id, service=other_service.id)
    integration, _, service, actor = identity
    admin.update_source(
        integration.id,
        source.id,
        SourceUpdate(
            expected_revision=revision(integration),
            gitlab_mappings=[
                {
                    "project_id": 42,
                    "environment": "production",
                    "service_ids": [service.id, other_service.id],
                },
                {
                    "project_id": 43,
                    "environment": "staging",
                    "service_ids": [service.id],
                },
            ],
        ),
        actor_id=actor.id,
    )
    assert send(client, gitlab).json["references"]["total"] == 2
    assert (
        send(
            client, gitlab, body(project={"id": 43}, environment="staging")
        ).status_code
        == 201
    )
    assert Change.select().count() == 2


def test_external_ids_are_not_limited_to_ir_integer_ids(client, gitlab):
    source = gitlab[1]
    source.gitlab_mappings = [
        {
            "project_id": 3000000000,
            "environment": "production",
            "service_ids": [gitlab[0][2].id],
        }
    ]
    source.save()
    response = send(
        client, gitlab, body(project={"id": 3000000000}, deployment_id=9007199254740992)
    )
    assert response.status_code == 201
    assert response.json["change_id"] == "gitlab:3000000000:9007199254740992"


@pytest.mark.parametrize(
    "patch",
    [
        {"project": {"id": "42"}},
        {"deployment_id": True},
        {"status": "unknown"},
        {"status_changed_at": "2026-01-01 12:00:00"},
        {"status_changed_at": None},
        {"deployable_url": "javascript:alert(1)"},
        {"environment": ""},
        {"object_kind": "pipeline"},
    ],
)
def test_invalid_native_payload_rejected(client, gitlab, patch):
    assert send(client, gitlab, body(**patch)).status_code == 422
    assert ChangeEvent.select().count() == 0


def test_bounded_parser_and_event_header(client, gitlab):
    assert (
        send(client, gitlab, headers={"X-Gitlab-Token": gitlab[4]}).status_code == 422
    )
    headers = {"X-Gitlab-Token": gitlab[4], "X-Gitlab-Event": "Deployment Hook"}
    url = f"/api/change-events/gitlab/{gitlab[1].id}"
    assert (
        client.post(
            url,
            data='{"project":1,"project":2}',
            content_type="application/json",
            headers=headers,
        ).status_code
        == 400
    )
    assert (
        client.post(
            url, data=" " * 262145, content_type="application/json", headers=headers
        ).status_code
        == 413
    )
    assert send(client, gitlab, body(extra="\x00")).status_code == 422


def test_mapping_edit_validation_and_optimistic_lock(client, gitlab, admin_headers):
    integration, source, service, _ = gitlab[0]
    url = f"/api/admin/change-integrations/{integration.id}/sources/{source.id}"
    mapping = {
        "project_id": 42,
        "environment": "production",
        "service_ids": [service.id],
    }
    current = revision(integration)
    for mappings in ([mapping, mapping], [{**mapping, "service_ids": []}]):
        assert (
            client.patch(
                url,
                json={"expected_revision": current, "gitlab_mappings": mappings},
                headers=admin_headers,
            ).status_code
            == 400
        )
    assert (
        client.patch(
            url,
            json={"expected_revision": current, "ordering_mode": "sequence"},
            headers=admin_headers,
        ).status_code
        == 409
    )
    assert (
        client.patch(
            url,
            json={"expected_revision": current - 1, "gitlab_mappings": []},
            headers=admin_headers,
        ).status_code
        == 409
    )
    saved = client.patch(
        url,
        json={"expected_revision": current, "gitlab_mappings": []},
        headers=admin_headers,
    )
    assert saved.status_code == 200
    assert saved.json["sources"][0]["gitlab_mappings"] == []


def test_service_options_follow_changed_grants(client, gitlab, admin_headers):
    integration, source, service, _ = gitlab[0]
    url = f"/api/admin/change-integrations/targets?integration_id={integration.id}&source_id={source.id}"
    assert [
        row["id"] for row in client.get(url, headers=admin_headers).json["services"]
    ] == [service.id]
    gitlab[2].active = False
    gitlab[2].save()
    assert client.get(url, headers=admin_headers).json["services"] == []


def test_owned_mapping_cannot_reference_another_group(client, gitlab, admin_headers):
    integration, source, service, _ = gitlab[0]
    integration.owner_group = source.owner_team.group_id
    integration.save()
    foreign = create_service(create_team(create_group()))
    url = f"/api/admin/change-integrations/{integration.id}/sources/{source.id}"
    denied = client.patch(
        url,
        headers=admin_headers,
        json={
            "expected_revision": revision(integration),
            "gitlab_mappings": [
                {
                    "project_id": 42,
                    "environment": "production",
                    "service_ids": [foreign.id],
                }
            ],
        },
    )
    assert denied.status_code == 403
    assert ChangeSource.get_by_id(source.id).gitlab_mappings[0]["service_ids"] == [
        service.id
    ]


def test_native_openapi_and_translations():
    import json
    from pathlib import Path

    from app.api.openapi.spec import build_openapi_spec

    spec = build_openapi_spec()
    operation = spec["paths"]["/api/change-events/gitlab/{source_id}"]["post"]
    assert operation["security"] == [{"gitlabChangeToken": []}, {"bearerAuth": []}]
    assert (
        spec["components"]["securitySchemes"]["gitlabChangeToken"]["name"]
        == "X-Gitlab-Token"
    )
    schema = spec["components"]["schemas"]["GitLabDeployment"]
    assert "status_changed_at" in schema["required"]
    project_ref = schema["properties"]["project"]["$ref"].split("/")[-1]
    assert project_ref in spec["components"]["schemas"]
    source = spec["paths"][
        "/api/admin/change-integrations/{integration_id}/sources/{source_id}"
    ]["patch"]
    properties = source["requestBody"]["content"]["application/json"]["schema"][
        "properties"
    ]
    assert properties["gitlab_mappings"]["items"]["required"] == [
        "project_id",
        "environment",
        "service_ids",
    ]
    root = Path(__file__).resolve().parents[2] / "app/static/i18n"
    baseline = json.loads(
        (root / "en/change_integrations.json").read_text(encoding="utf-8")
    )
    keys = {key for key in baseline if key.startswith("ci.gitlab_")}
    assert keys
    for locale in ("ru", "de", "fr", "es", "zh"):
        translated = json.loads(
            (root / locale / "change_integrations.json").read_text(encoding="utf-8")
        )
        assert {key for key in translated if key.startswith("ci.gitlab_")} == keys
        assert all(translated[key].strip() for key in keys)


def test_native_transaction_retry(client, gitlab, monkeypatch):
    original = ingestion._ingest_once
    calls = []

    def fail_once(*args):
        calls.append(1)
        result = original(*args)
        if len(calls) == 1:
            raise OperationalError("database is locked")
        return result

    monkeypatch.setattr(ingestion, "_ingest_once", fail_once)
    monkeypatch.setattr(
        ingestion, "_transient", lambda error: str(error) == "database is locked"
    )
    result = send(client, gitlab)
    assert result.status_code == 201, result.json
    assert len(calls) == 2
    assert ChangeEvent.select().count() == 1
    assert Change.get().revision == 1


def test_legacy_source_migration_is_idempotent(tmp_path, monkeypatch):
    migration = import_module("app.migrations.20261113010000_gitlab_change_mappings")
    db = SqliteDatabase(tmp_path / "legacy-gitlab.db")
    monkeypatch.setattr(migration, "init_database", lambda: db)
    try:
        db.execute_sql(
            "CREATE TABLE change_source (id INTEGER PRIMARY KEY, source TEXT)"
        )
        db.execute_sql("INSERT INTO change_source VALUES (1, 'existing')")
        migration.upgrade()
        migration.upgrade()
        migration.downgrade()
        assert db.execute_sql(
            "SELECT source, gitlab_mappings FROM change_source"
        ).fetchall() == [("existing", "[]")]
    finally:
        db.close()
