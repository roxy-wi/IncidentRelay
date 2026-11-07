"""Atomic intake contracts and permission failures on both supported databases."""

import itertools
import json
from datetime import timedelta

import pytest
from peewee import OperationalError

from app.api.schemas.change_events import ChangeEventInput
from app.api.schemas.change_integrations import (
    GrantUpdate,
    MachineTokenCreate,
    SourceUpdate,
)
from app.modules.common import utc_now
from app.modules.db.models import (
    Change,
    ChangeEvent,
    ChangeJob,
    SystemSettings,
    ChangeService,
    ChangeServiceReference,
    Service,
    Team,
)
from app.services.change_intelligence import administration as admin, ingestion
from app.services.change_intelligence.projection import project_events
from app.settings import Config
from tests.factories import create_group, create_service, create_team
from tests.integrations.test_change_integrations import (
    credential,
    grant,
    revision,
    setup_identity,
)

__all__ = ["setup_identity"]
URL = "/api/change-events"


def event_payload(identity, **overrides):
    _, source, service, _ = identity
    payload = {
        "schema_version": 1,
        "event_id": "event-1",
        "change_id": "build-1",
        "owner_team_id": source.owner_team_id,
        "source": source.source,
        "kind": "deployment",
        "event_type": "change.succeeded",
        "occurred_at": "2026-01-01T12:00:00Z",
        "title": "Release one",
        "changed_service_ids": [service.id],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def intake(setup_identity):
    SystemSettings.update(change_intake_enabled=True).execute()
    permission = grant(setup_identity)
    token, raw = credential(setup_identity)
    return setup_identity, permission, token, raw


def send(client, intake, **overrides):
    identity, _, _, raw = intake
    return client.post(
        URL,
        json=event_payload(identity, **overrides),
        headers={"Authorization": f"Bearer {raw}"},
    )


def test_disabled_by_default_and_no_public_auth_bypass(
    client, intake, admin_headers, monkeypatch
):
    SystemSettings.update(change_intake_enabled=False).execute()
    assert send(client, intake).status_code == 404
    SystemSettings.update(change_intake_enabled=True).execute()
    for optional_auth in (False, True):
        monkeypatch.setattr(Config, "API_AUTH_REQUIRED", optional_auth)
        for headers in ({}, admin_headers):
            assert (
                client.post(
                    URL, json=event_payload(intake[0]), headers=headers
                ).status_code
                == 401
            )
    assert ChangeEvent.select().count() == 0


def test_accept_retry_canonical_forms_and_conflict(client, intake):
    first = send(client, intake)
    assert first.status_code == 201, first.json
    assert first.json["status"] == "succeeded"
    assert first.json["correlation_status"] == "queued"
    assert first.json["references"] == {"total": 1, "resolved": 1, "pending": 0}
    identity, _, _, raw = intake
    body = event_payload(identity, occurred_at="2026-01-01T15:00:00.000000+03:00")
    body.pop("changed_service_ids")
    body["changed_services"] = [{"service_id": identity[2].id}] * 2
    retry = client.post(URL, json=body, headers={"Authorization": f"Bearer {raw}"})
    assert retry.status_code == 200
    assert retry.json == first.json
    assert retry.headers["Cache-Control"] == "no-store"
    assert send(client, intake, title="different").status_code == 409
    assert send(client, intake, change_id="another-operation").status_code == 409
    assert ChangeEvent.select().count() == 1
    assert Change.get().revision == 1
    job = ChangeJob.get(ChangeJob.job_type == "resolve_references")
    assert job.requested_generation == 1


def test_rotation_retry_and_current_source_authority(client, intake):
    assert send(client, intake).status_code == 201
    identity, _, old, _ = intake
    integration, source, _, actor = identity
    _, raw = admin.issue_token(
        integration.id,
        MachineTokenCreate(
            expected_revision=revision(integration),
            name="replacement",
        ),
        actor_id=actor.id,
        rotate_token_id=old.id,
    )
    assert send(client, intake).status_code == 401
    updated = (*intake[:3], raw)
    assert send(client, updated).status_code == 200
    admin.update_source(
        integration.id,
        source.id,
        SourceUpdate(
            expected_revision=revision(integration),
            active=False,
        ),
        actor_id=actor.id,
    )
    assert send(client, updated).status_code == 403
    assert ChangeEvent.select().count() == 1


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"owner_team_id": True},
        {"owner_team_slug": "also-owner"},
        {"owner_team_id": None},
        {"title": None},
        {"title": " "},
        {"event_id": ""},
        {"source_sequence": True},
        {"source_sequence": -1},
        {"source_sequence": 1.0},
        {"source_sequence": None},
        {"source_sequence": 1},
        {"occurred_at": "2026-01-01T12:00:00"},
        {"occurred_at": 123456},
        {"occurred_at": "2026-01-01T12:00:00.1234567Z"},
        {"occurred_at": "2026-01-01T12:00:00+00:99"},
        {"occurred_at": "0001-01-01T00:00:00+01:00"},
        {"external_url": "javascript:alert(1)"},
        {"external_url": "https://user:secret@example.com"},
        {"changed_services": []},
        {"changed_service_ids": [True]},
        {"changed_service_ids": list(range(1, 102))},
        {"unknown": "value"},
        {"details": {"value": "x" * 65536}},
    ],
)
def test_strict_invalid_input_leaves_no_rows(client, intake, mutation):
    result = send(client, intake, **mutation)
    assert result.status_code == 422, result.json
    assert Change.select().count() == 0
    assert ChangeEvent.select().count() == 0


@pytest.mark.parametrize(
    "raw,status",
    [
        ('{"schema_version":1,"schema_version":1}', 400),
        ('{"details":{"value":NaN}}', 400),
        ("[]", 422),
        ("[" * 100 + "]" * 100, 422),
        (" " * 262145, 413),
    ],
    ids=["duplicate-key", "nan", "array", "deep-array", "oversized"],
)
def test_malformed_and_bounded_body(client, intake, raw, status):
    response = client.post(
        URL,
        data=raw,
        content_type="application/json",
        headers={"Authorization": f"Bearer {intake[3]}"},
    )
    assert response.status_code == status
    assert Change.select().count() == 0


def test_details_depth_future_time_and_redaction(client, intake):
    details = {}
    for _ in range(12):
        details = {"nested": details}
    assert send(client, intake, details=details).status_code == 422
    future = (utc_now() + timedelta(minutes=6)).isoformat() + "Z"
    assert send(client, intake, occurred_at=future).status_code == 422
    assert send(client, intake, details={"password": "very-secret"}).status_code == 201
    row = ChangeEvent.get()
    assert "very-secret" not in json.dumps(row.request_snapshot)
    assert row.details["password"] == "***REDACTED***"
    assert (
        send(client, intake, details={"password": "different-secret"}).status_code
        == 409
    )


def test_terminal_conflict_late_start_metadata_and_later_winner(client, intake):
    assert send(client, intake).status_code == 201
    assert send(client, intake, event_id="fail", event_type="change.failed").json[
        "lifecycle_conflict"
    ]
    row = Change.get()
    assert row.status == "unknown" and row.completed_at is None
    assert (
        send(
            client,
            intake,
            event_id="late-start",
            event_type="change.started",
            occurred_at="2026-01-01T13:00:00Z",
        ).json["status"]
        == "unknown"
    )
    assert (
        send(
            client,
            intake,
            event_id="final",
            event_type="change.rolled_back",
            occurred_at="2026-01-01T14:00:00Z",
        ).json["status"]
        == "rolled_back"
    )
    assert (
        send(
            client,
            intake,
            event_id="late-again",
            event_type="change.started",
            occurred_at="2026-01-01T15:00:00Z",
        ).json["status"]
        == "rolled_back"
    )
    assert not Change.get().lifecycle_conflict
    assert Change.get().revision == 5


def test_projection_permutations_are_equal(client, intake):
    for fields in [
        {
            "event_id": "start",
            "event_type": "change.started",
            "occurred_at": "2026-01-01T11:00:00Z",
            "description": "original",
        },
        {"event_id": "z", "description": None},
        {"event_id": "a", "title": "A"},
        {
            "event_id": "end",
            "event_type": "change.failed",
            "occurred_at": "2026-01-01T13:00:00Z",
        },
    ]:
        assert send(client, intake, **fields).status_code == 201
    events = list(ChangeEvent.select())
    results = [
        project_events(list(order), "timestamp", "fallback")
        for order in itertools.permutations(events)
    ]
    assert all(result == results[0] for result in results)
    assert results[0]["description"] is None
    assert results[0]["status"] == "failed"


def test_equal_terminal_outcomes_and_metadata_tie_use_event_id(client, intake):
    assert (
        send(client, intake, event_id="z", title="Z", description="keep").status_code
        == 201
    )
    assert (
        send(client, intake, event_id="a", title="A", description="old").status_code
        == 201
    )
    change = Change.get()
    assert change.title == "Z" and change.description == "keep"
    assert change.status == "succeeded" and not change.lifecycle_conflict


def test_service_only_grant_cannot_create_pending_reference(
    client, setup_identity
):
    SystemSettings.update(change_intake_enabled=True).execute()
    grant(setup_identity, service=setup_identity[2].id)
    _, raw = credential(setup_identity)
    body = event_payload(setup_identity)
    body.pop("changed_service_ids")
    body["changed_services"] = [{"service_slug": "not-provisioned"}]
    assert (
        client.post(
            URL, json=body, headers={"Authorization": f"Bearer {raw}"}
        ).status_code
        == 403
    )
    assert Change.select().count() == 0


def test_absent_null_fields_and_initial_title(client, intake):
    body = event_payload(intake[0], event_type="change.updated")
    body.pop("title")
    headers = {"Authorization": f"Bearer {intake[3]}"}
    assert client.post(URL, json=body, headers=headers).status_code == 201
    assert Change.get().title == "build-1"
    assert Change.get().status == "unknown"
    assert (
        send(
            client,
            intake,
            event_id="named",
            title="Name",
            description="Description",
            external_url="https://example.com/build",
        ).status_code
        == 201
    )
    body.update(event_id="update", occurred_at="2026-01-01T13:00:00Z", description=None)
    assert client.post(URL, json=body, headers=headers).status_code == 201
    change = Change.get()
    assert change.title == "Name" and change.description is None
    assert change.external_url == "https://example.com/build"


def test_sequence_order_snapshot_and_conflicts(client, intake):
    identity = intake[0]
    integration, source, _, actor = identity
    admin.update_source(
        integration.id,
        source.id,
        SourceUpdate(expected_revision=revision(integration), ordering_mode="sequence"),
        actor_id=actor.id,
    )
    assert send(client, intake).status_code == 422
    assert send(client, intake, source_sequence=10).status_code == 201
    admin.update_source(
        integration.id,
        source.id,
        SourceUpdate(
            expected_revision=revision(integration), ordering_mode="timestamp"
        ),
        actor_id=actor.id,
    )
    assert (
        send(
            client,
            intake,
            event_id="gap",
            source_sequence=2,
            event_type="change.started",
            occurred_at="2026-01-01T13:00:00Z",
        ).json["status"]
        == "succeeded"
    )
    assert {item["code"] for item in Change.get().diagnostics} == {
        "sequence_time_inversion",
        "completion_before_start",
    }
    assert send(client, intake, event_id="reuse", source_sequence=2).status_code == 409
    assert send(client, intake, event_id="missing-seq").status_code == 422
    assert (
        send(
            client, intake, event_id="changed-kind", kind="other", source_sequence=11
        ).status_code
        == 409
    )
    assert (
        send(
            client,
            intake,
            event_id="changed-env",
            environment="production",
            source_sequence=11,
        ).status_code
        == 409
    )
    assert (
        send(client, intake, event_id="next-operation", change_id="build-2").status_code
        == 201
    )


def test_pending_namespace_aliases_and_no_rebinding(client, intake):
    identity = intake[0]
    service = identity[2]
    body = event_payload(identity)
    body.pop("changed_service_ids")
    body["changed_services"] = [
        {"service_id": service.id},
        {"service_slug": service.slug},
        {"service_slug": "future-db"},
    ]
    headers = {"Authorization": f"Bearer {intake[3]}"}
    result = client.post(URL, json=body, headers=headers)
    assert result.status_code == 201, result.json
    assert result.json["mapping_status"] == "partially_mapped"
    assert ChangeService.select().count() == 1
    pending = ChangeServiceReference.get(
        ChangeServiceReference.resolution_status == "pending_resolution"
    )
    assert pending.namespace_team_id == service.team_id
    assert pending.requested_service_slug == "future-db"
    old_slug = service.slug
    Service.update(slug="renamed").where(Service.id == service.id).execute()
    replacement = create_service(service.team, slug=old_slug)
    body.update(event_id="again", changed_services=[{"service_slug": old_slug}])
    assert client.post(URL, json=body, headers=headers).status_code == 201
    assert ChangeService.get().service_id == service.id
    assert ChangeService.get().service_id != replacement.id


def test_foreign_grants_and_reference_only_trust(client, intake):
    foreign = create_service(create_team(create_group()))
    body = event_payload(intake[0], affected_services=[{"service_id": foreign.id}])
    headers = {"Authorization": f"Bearer {intake[3]}"}
    assert client.post(URL, json=body, headers=headers).status_code == 403
    assert Change.select().count() == 0
    grant(intake[0], capability="reference", team=foreign.team_id, service=foreign.id)
    assert client.post(URL, json=body, headers=headers).status_code == 201
    relation = ChangeService.get(ChangeService.relation_type == "reported_affected")
    assert relation.verification_state == "unverified"
    grant(
        intake[0],
        capability="reported_affected",
        team=foreign.team_id,
        service=foreign.id,
    )
    body["event_id"] = "trusted"
    assert client.post(URL, json=body, headers=headers).status_code == 201
    assert ChangeService.get_by_id(relation.id).verification_state == "trusted"
    body.update(event_id="no-assertion-right", changed_service_ids=[foreign.id])
    assert client.post(URL, json=body, headers=headers).status_code == 403


def test_invalid_id_scope_uniform_denial_and_no_global_slug_lookup(client, intake):
    identity = intake[0]
    team_id = identity[2].team_id
    assert send(client, intake, changed_service_ids=[2147483647]).status_code == 403
    body = event_payload(identity)
    body.pop("changed_service_ids")
    body["changed_services"] = [{"team_id": team_id, "service_id": 2147483647}]
    headers = {"Authorization": f"Bearer {intake[3]}"}
    assert client.post(URL, json=body, headers=headers).status_code == 422
    foreign = create_service(create_team(create_group()), slug="foreign-only")
    body["changed_services"] = [{"team_id": team_id, "service_id": foreign.id}]
    response = client.post(URL, json=body, headers=headers)
    assert response.status_code == 422
    assert response.json["message"] == "Unknown Service ID in the permitted namespace"
    for ref in (
        {"service_id": foreign.id},
        {"team_id": foreign.team_id, "service_slug": "absent"},
    ):
        body["changed_services"] = [ref]
        assert client.post(URL, json=body, headers=headers).status_code == 403
    body["changed_services"] = [{"service_slug": foreign.slug}]
    assert client.post(URL, json=body, headers=headers).status_code == 201
    assert ChangeService.select().count() == 0
    assert ChangeServiceReference.get().namespace_team_id == team_id


def test_old_owner_slug_is_not_a_retry_bypass(client, intake):
    body = event_payload(intake[0])
    team_id = body.pop("owner_team_id")
    body["owner_team_slug"] = Team.get_by_id(team_id).slug
    headers = {"Authorization": f"Bearer {intake[3]}"}
    assert client.post(URL, json=body, headers=headers).status_code == 201
    Team.update(slug="new-owner-name").where(Team.id == team_id).execute()
    assert client.post(URL, json=body, headers=headers).status_code == 403


@pytest.mark.parametrize(
    "step",
    ["parent", "event", "reference", "service", "projection", "aggregate", "job"],
)
def test_each_failed_write_rolls_back_then_retries_once(
    client, intake, monkeypatch, step
):
    targets = {
        "parent": (Change, "create"),
        "event": (ChangeEvent, "create"),
        "reference": (ChangeServiceReference, "create"),
        "service": (ChangeService, "create"),
        "projection": (ingestion, "project_events"),
        "aggregate": (Change, "update"),
        "job": (ingestion.changes_repo, "request_job"),
    }

    def fail(*args, **kwargs):
        raise RuntimeError("injected failure")

    with monkeypatch.context() as patch:
        patch.setattr(*targets[step], fail)
        assert send(client, intake).status_code == 500
    for model in (Change, ChangeEvent, ChangeServiceReference, ChangeService):
        assert model.select().count() == 0
    assert (
        not ChangeJob.select()
        .where(ChangeJob.job_type == "resolve_references")
        .exists()
    )
    assert send(client, intake).status_code == 201
    assert send(client, intake).status_code == 200
    assert ChangeEvent.select().count() == 1


def test_quota_and_history_limits_keep_exact_retries(client, intake):
    SystemSettings.update(change_events_per_minute=1).execute()
    assert send(client, intake).status_code == 201
    assert send(client, intake).status_code == 200
    assert send(client, intake, event_id="too-fast").status_code == 429
    SystemSettings.update(change_events_per_minute=600).execute()
    SystemSettings.update(change_events_per_change=1).execute()
    assert send(client, intake, event_id="too-many").status_code == 422


def test_transient_errors_retry_only_with_budget(intake, monkeypatch, db):
    calls = []
    real = ingestion._ingest_once

    def transient(*args):
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("database is locked")
        return real(*args)

    monkeypatch.setattr(ingestion, "_ingest_once", transient)
    monkeypatch.setattr(
        ingestion, "_transient", lambda error: str(error) == "database is locked"
    )
    monkeypatch.setattr(ingestion.time, "sleep", lambda delay: None)
    payload = ChangeEventInput.model_validate(event_payload(intake[0]))
    assert ingestion.ingest_event(payload, intake[3])[1]
    assert len(calls) == 3

    def permanent(*args):
        raise OperationalError("missing table")

    monkeypatch.setattr(ingestion, "_ingest_once", permanent)
    with pytest.raises(OperationalError, match="missing table"):
        ingestion.ingest_event(payload, intake[3])

    def always_busy(*args):
        raise OperationalError("database is locked")

    monkeypatch.setattr(ingestion, "_ingest_once", always_busy)
    with pytest.raises(ingestion.ChangeIntakeBusy):
        ingestion.ingest_event(payload, intake[3])


def test_grant_revocation_keeps_retry_but_rolls_back_new_event(client, intake):
    assert send(client, intake).status_code == 201
    identity, permission, _, _ = intake
    integration, source, _, actor = identity
    admin.update_grant(
        integration.id,
        source.id,
        permission.id,
        GrantUpdate(
            expected_revision=revision(integration),
            active=False,
        ),
        actor_id=actor.id,
    )
    assert send(client, intake).status_code == 200
    assert send(client, intake, event_id="denied").status_code == 403
    assert ChangeEvent.select().count() == 1
    assert Change.get().revision == 1


def test_pending_resolves_on_new_event_without_rewriting_first_evidence(client, intake):
    body = event_payload(intake[0])
    body.pop("changed_service_ids")
    body["changed_services"] = [{"service_slug": "future-service"}]
    headers = {"Authorization": f"Bearer {intake[3]}"}
    assert client.post(URL, json=body, headers=headers).status_code == 201
    original = ChangeEvent.get()
    reference = ChangeServiceReference.get()
    created = create_service(intake[0][2].team, slug="future-service")
    body["event_id"] = "after-provisioning"
    assert client.post(URL, json=body, headers=headers).status_code == 201
    reference = ChangeServiceReference.get_by_id(reference.id)
    assert reference.resolved_service_id == created.id
    assert reference.first_event_id == original.id
    assert ChangeService.get().first_reference_id == reference.id
    assert (
        ChangeEvent.get_by_id(original.id).request_snapshot == original.request_snapshot
    )


@pytest.mark.parametrize(
    "reference",
    [
        {"service_slug": "bad_slug"},
        {"service_slug": "valid", "service_id": 1},
        {"service_id": 1, "team_id": 1, "team_slug": "owner"},
        {"service_slug": "valid", "team_id": None},
        {},
    ],
)
def test_invalid_reference_shapes(client, intake, reference):
    body = event_payload(intake[0])
    body.pop("changed_service_ids")
    body["changed_services"] = [reference]
    response = client.post(
        URL, json=body, headers={"Authorization": f"Bearer {intake[3]}"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("description", "\x00"),
        ("details", {"key": "\ud800"}),
        ("actor", {"type": "automation", "name": "\x00"}),
    ],
)
def test_text_portable_to_postgresql(client, intake, field, value):
    assert send(client, intake, **{field: value}).status_code == 422


def test_environment_normalization_and_digest_alias_distinction(client, intake):
    assert send(client, intake, environment=" production ").status_code == 201
    assert send(client, intake, environment="production").status_code == 200
    body = event_payload(intake[0], environment="production")
    body.pop("changed_service_ids")
    body["changed_services"] = [{"service_slug": intake[0][2].slug}]
    assert (
        client.post(
            URL, json=body, headers={"Authorization": f"Bearer {intake[3]}"}
        ).status_code
        == 409
    )


def test_openapi_matches_intake_contract():
    from app.api.openapi.spec import build_openapi_spec

    spec = build_openapi_spec()
    operation = spec["paths"][URL]["post"]
    assert set(operation["responses"]) >= {
        "200",
        "201",
        "401",
        "403",
        "409",
        "422",
        "429",
        "503",
    }
    schema = spec["components"]["schemas"]["ChangeEventInput"]
    assert "occurred_at" in schema["required"]
    assert schema["properties"]["source_sequence"]["type"] == "integer"
    assert schema["properties"]["owner_team_id"]["minimum"] == 0
    assert schema["properties"]["owner_team_id"]["exclusiveMinimum"] is True
    assert schema["properties"]["description"]["nullable"]
    assert "nullable" not in schema["properties"]["title"]
