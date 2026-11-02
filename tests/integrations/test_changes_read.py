"""Read contracts, SQL visibility and revocation across human/token boundaries."""

import json
import uuid

import pytest

from app.api.schemas.change_events import ChangeEventInput
from app.api.schemas.change_integrations import (
    GrantUpdate,
    IntegrationUpdate,
    SourceUpdate,
)
from app.modules.db import services_repo, tokens_repo
from app.modules.db.models import (
    Change,
    ChangeEvent,
    ChangeJob,
    ChangeServiceReference,
    TeamUser,
)
from app.services.change_intelligence import administration as admin, ingestion
from app.services.change_intelligence.catalog import graph_change
from app.services.integrations.auth import hash_token
from app.settings import Config
from tests.factories import (
    add_user_to_team,
    create_group,
    create_service,
    create_team,
    create_user,
    unique,
)
from tests.integrations.test_change_events import event_payload, intake, setup_identity
from tests.integrations.test_change_integration_groups import headers
from tests.integrations.test_change_integrations import grant, revision
from tests.integrations.test_change_worker import process_resolution

__all__ = ["intake", "setup_identity"]
BASE = "/api/changes"


def reader(team):
    user = create_user(group=team.group, group_role="viewer")
    add_user_to_team(team, user, role="viewer")
    return user


@pytest.fixture
def changes(intake):
    identity = intake[0]
    foreign = create_service(create_team(create_group()), name="Visible checkout")
    permission = grant(identity, capability="reported_affected", team=foreign.team_id)
    body = event_payload(
        identity,
        title="PRIVATE release <script>unsafe()</script>",
        description="PRIVATE release description",
        environment="production",
        external_url="https://ci.example.test/private-build",
        actor={"type": "ci", "name": "PRIVATE actor"},
        details={"note": "PRIVATE detail"},
        affected_services=[{"service_id": foreign.id, "team_id": foreign.team_id}],
    )
    ingestion.ingest_event(ChangeEventInput.model_validate(body), intake[3])
    change = Change.get()
    process_resolution(change)
    return {
        "change": Change.get(),
        "owner": reader(identity[2].team),
        "foreign": reader(foreign.team),
        "service": foreign,
        "permission": permission,
        "intake": intake,
        "body": body,
    }


def url(changes, suffix=""):
    return f"{BASE}/{changes['change'].uid}{suffix}"


def test_owner_history_and_scoped_service_diagnostics(client, changes):
    auth = headers(changes["owner"])
    detail = client.get(url(changes), headers=auth)
    assert detail.status_code == 200, detail.json
    assert detail.json["projection"] == "full"
    assert detail.json["processing"]["current"]
    assert detail.json["description"] == "PRIVATE release description"
    assert detail.json["reference_counts"] == {"resolved": 1}
    services = client.get(url(changes, "/services"), headers=auth).json
    assert services["pagination"]["total"] == 1
    assert services["references"]["pagination"]["total"] == 1
    assert "Visible checkout" not in json.dumps(services)
    events = client.get(url(changes, "/events"), headers=auth).json
    assert events["items"][0]["details"] == {"note": "PRIVATE detail"}
    assert "submitted_references" not in events["items"][0]
    assert "request_digest" not in events["items"][0]
    assert "ingest_token" not in json.dumps(events)
    assert detail.headers["Cache-Control"] == "no-store"


def test_safe_projection_is_whitelisted_on_list_detail_and_services(client, changes):
    auth = headers(changes["foreign"])
    listed = client.get(BASE, headers=auth)
    assert listed.status_code == 200, listed.json
    assert listed.json["pagination"]["total"] == 1
    safe = listed.json["items"][0]
    assert set(safe) == {
        "uid",
        "projection",
        "title",
        "kind",
        "occurred_at",
        "services",
    }
    assert safe["projection"] == "safe" and safe["title"] == "Related change"
    assert safe["services"][0]["service"]["id"] == changes["service"].id
    assert client.get(url(changes), headers=auth).json == safe
    assert "PRIVATE" not in json.dumps(safe)
    assert client.get(url(changes, "/events"), headers=auth).status_code == 404
    services = client.get(url(changes, "/services"), headers=auth).json
    assert services["items"] == safe["services"]
    assert "references" not in services


@pytest.mark.parametrize(
    "query",
    [
        "search=PRIVATE",
        "search=build-1",
        "status=succeeded",
        "source=deploy",
        "environment=production",
    ],
)
def test_private_filters_never_match_a_safe_projection(client, changes, query):
    response = client.get(BASE + "?" + query, headers=headers(changes["foreign"]))
    assert response.status_code == 200
    assert response.json["items"] == [] and response.json["pagination"]["total"] == 0
    assert (
        client.get(BASE + "?" + query, headers=headers(changes["owner"])).json[
            "pagination"
        ]["total"]
        == 1
    )


def test_service_id_and_namespaced_slug_have_equal_visibility(client, changes):
    service = changes["service"]
    auth = headers(changes["foreign"])
    by_id = client.get(BASE, query_string={"service_id": service.id}, headers=auth)
    by_slug = client.get(
        BASE,
        query_string={"service_slug": service.slug, "team_slug": service.team.slug},
        headers=auth,
    )
    assert by_id.status_code == by_slug.status_code == 200
    assert by_id.json == by_slug.json
    nested = client.get(f"/api/services/{service.id}/changes", headers=auth)
    assert nested.json == by_id.json
    scoped = client.get(
        BASE, query_string={"scope_team_id": service.team_id}, headers=auth
    )
    assert scoped.json == by_id.json
    hidden = changes["intake"][0][2]
    forbidden = client.get(BASE, query_string={"service_id": hidden.id}, headers=auth)
    missing = client.get(BASE + "?service_id=2147483647", headers=auth)
    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json == missing.json
    assert (
        client.get(
            BASE,
            query_string={"service_slug": hidden.slug, "team_id": hidden.team_id},
            headers=auth,
        ).json
        == missing.json
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "grant",
        "source",
        "integration",
        "graph",
        "move",
        "partial",
        "new_generation",
        "dead",
    ],
)
def test_stale_or_revoked_links_disappear_before_worker_and_pagination(
    client, changes, mutation
):
    identity = changes["intake"][0]
    integration, source, _, actor = identity
    if mutation == "grant":
        admin.update_grant(
            integration.id,
            source.id,
            changes["permission"].id,
            GrantUpdate(expected_revision=revision(integration), active=False),
            actor_id=actor.id,
        )
    elif mutation == "source":
        admin.update_source(
            integration.id,
            source.id,
            SourceUpdate(expected_revision=revision(integration), active=False),
            actor_id=actor.id,
        )
    elif mutation == "integration":
        admin.update_integration(
            integration.id,
            IntegrationUpdate(expected_revision=revision(integration), active=False),
            actor_id=actor.id,
        )
    elif mutation == "graph":
        with graph_change():
            pass
    elif mutation == "move":
        services_repo.update_service(
            changes["service"].id, {"team": create_team(create_group()).id}
        )
    else:
        updates = (
            {"cursor": {"after_id": 1}}
            if mutation == "partial"
            else (
                {"requested_generation": ChangeJob.requested_generation + 1}
                if mutation == "new_generation"
                else {"state": "dead"}
            )
        )
        ChangeJob.update(**updates).where(
            ChangeJob.job_type == "resolve_references"
        ).execute()
    auth = headers(changes["foreign"])
    listed = client.get(BASE + "?page_size=1", headers=auth)
    assert listed.status_code == 200
    assert listed.json["items"] == [] and listed.json["pagination"]["total"] == 0
    assert client.get(url(changes), headers=auth).status_code == 404
    assert (
        client.get(url(changes), headers=headers(changes["owner"])).status_code == 200
    )


def test_unverified_affected_claim_does_not_grant_visibility(client, changes):
    identity = changes["intake"][0]
    admin.update_grant(
        identity[0].id,
        identity[1].id,
        changes["permission"].id,
        GrantUpdate(expected_revision=revision(identity[0]), capability="reference"),
        actor_id=identity[3].id,
    )
    body = {**changes["body"], "event_id": "reference-only"}
    ingestion.ingest_event(ChangeEventInput.model_validate(body), changes["intake"][3])
    process_resolution(Change.get())
    assert (
        client.get(BASE, headers=headers(changes["foreign"])).json["pagination"][
            "total"
        ]
        == 0
    )


def test_sql_pagination_deduplicates_aliases_and_excludes_hidden_changes(
    client, changes
):
    body = {
        **changes["body"],
        "event_id": "alias",
        "affected_services": [
            {
                "service_slug": changes["service"].slug,
                "team_id": changes["service"].team_id,
            }
        ],
    }
    ingestion.ingest_event(ChangeEventInput.model_validate(body), changes["intake"][3])
    process_resolution(Change.get())
    for index in range(3):
        body = event_payload(
            changes["intake"][0],
            change_id=f"private-{index}",
            event_id=f"private-{index}",
        )
        ingestion.ingest_event(
            ChangeEventInput.model_validate(body), changes["intake"][3]
        )
    auth = headers(changes["foreign"])
    first = client.get(BASE + "?page_size=1", headers=auth).json
    second = client.get(BASE + "?page_size=1&page=2", headers=auth).json
    assert first["pagination"]["total"] == 1 and len(first["items"]) == 1
    assert second["items"] == [] and second["pagination"]["total"] == 1


def personal(user, scopes, **restrictions):
    raw = unique("read-token")
    tokens_repo.create_api_token(
        "reader", raw[:12], hash_token(raw), scopes, user_id=user.id, **restrictions
    )
    return {"Authorization": f"Bearer {raw}"}


@pytest.mark.parametrize("auth_required", [False, True])
def test_authentication_and_scopes_are_required_even_with_optional_auth(
    client, changes, monkeypatch, auth_required
):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", auth_required)
    assert client.get(BASE).status_code == 401
    assert (
        client.get(
            BASE, headers={"Authorization": f"Bearer {changes['intake'][3]}"}
        ).status_code
        == 403
    )
    for scopes, status in [
        (["resources:read"], 403),
        (["changes:write"], 403),
        (["changes:read"], 200),
        (["*"], 200),
    ]:
        response = client.get(BASE, headers=personal(changes["owner"], scopes))
        assert response.status_code == status
    token = personal(changes["foreign"], ["changes:read"])
    nested = f"/api/services/{changes['service'].id}/changes"
    assert client.get(nested, headers=token).status_code == 403
    assert (
        client.get(
            nested,
            headers=personal(changes["foreign"], ["changes:read", "services:read"]),
        ).status_code
        == 200
    )


def test_personal_admin_token_remains_group_restricted_and_inactive_owner_is_denied(
    client, changes
):
    admin_user = changes["intake"][0][3]
    auth = personal(
        admin_user, ["changes:read"], group_id=changes["service"].team.group_id
    )
    assert client.get(url(changes), headers=auth).json["projection"] == "safe"
    admin_user.active = False
    admin_user.save()
    assert client.get(BASE, headers=auth).status_code == 401


def test_membership_revocation_and_missing_uids_have_uniform_404(client, changes):
    auth = headers(changes["foreign"])
    TeamUser.update(active=False).where(
        TeamUser.user == changes["foreign"].id
    ).execute()
    for suffix in ("", "/events", "/services"):
        denied = client.get(url(changes, suffix), headers=auth)
        absent = client.get(f"{BASE}/{uuid.uuid4()}{suffix}", headers=auth)
        assert denied.status_code == absent.status_code == 404
        assert denied.json == absent.json


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "page_size=101",
        "page=no",
        "page=1&page=2",
        "status=unknown-status",
        "service_slug=checkout",
        "team_id=1",
        "service_id=1&service_slug=checkout&team_id=1",
        "service_id=999999999999999999999999999999",
        "occurred_from=2026-01-01T00:00:00",
        "occurred_from=2026-01-02T00:00:00Z&occurred_to=2026-01-01T00:00:00Z",
        "unexpected=1",
    ],
)
def test_invalid_queries_are_bounded_and_do_not_echo_inputs(client, changes, query):
    response = client.get(BASE + "?" + query, headers=headers(changes["owner"]))
    assert response.status_code == 400
    assert response.json["message"] == "Invalid Change query parameters"


def test_read_does_not_modify_events_revisions_or_queue(client, changes):
    before = (
        [row.__data__ for row in ChangeEvent.select()],
        [row.__data__ for row in ChangeJob.select()],
        Change.get().revision,
    )
    for suffix in ("", "/events", "/services"):
        assert (
            client.get(
                url(changes, suffix), headers=headers(changes["owner"])
            ).status_code
            == 200
        )
    after = (
        [row.__data__ for row in ChangeEvent.select()],
        [row.__data__ for row in ChangeJob.select()],
        Change.get().revision,
    )
    assert before == after


def test_owner_diagnostics_show_pending_expired_and_dead_state(client, changes):
    from datetime import timedelta
    from app.modules.common import utc_now

    body = {
        **changes["body"],
        "event_id": "missing-service",
        "changed_services": [{"service_slug": "not-provisioned"}],
        "affected_services": [],
    }
    body.pop("changed_service_ids")
    ingestion.ingest_event(ChangeEventInput.model_validate(body), changes["intake"][3])
    process_resolution(Change.get())
    auth = headers(changes["owner"])
    detail = client.get(url(changes), headers=auth).json
    assert detail["reference_counts"]["pending_resolution"] == 1
    assert (
        detail["processing"]["state"] == "pending" and detail["processing"]["current"]
    )
    ChangeServiceReference.update(expires_at=utc_now() - timedelta(seconds=1)).where(
        ChangeServiceReference.resolved_service.is_null(True)
    ).execute()
    process_resolution(Change.get())
    assert (
        client.get(url(changes), headers=auth).json["reference_counts"]["expired"] == 1
    )
    ChangeJob.update(state="dead", last_error_class="internal_error").where(
        ChangeJob.job_type == "resolve_references"
    ).execute()
    assert client.get(url(changes), headers=auth).json["processing"] == {
        "state": "dead",
        "current": False,
        "error": "internal_error",
    }


def test_pending_service_becomes_visible_after_catalog_creation(client, changes):
    body = {
        **changes["body"],
        "event_id": "late-event",
        "change_id": "late-change",
        "affected_services": [
            {"team_id": changes["service"].team_id, "service_slug": "late-checkout"}
        ],
    }
    accepted = client.post(
        "/api/change-events",
        json=body,
        headers={"Authorization": f"Bearer {changes['intake'][3]}"},
    )
    assert accepted.status_code == 201, accepted.json
    change = Change.get(Change.external_change_id == "late-change")
    endpoint = f"{BASE}/{change.uid}"
    process_resolution(change)
    assert client.get(endpoint, headers=headers(changes["foreign"])).status_code == 404
    service = create_service(changes["service"].team, slug="late-checkout")
    process_resolution(Change.get_by_id(change.id))
    visible = client.get(endpoint, headers=headers(changes["foreign"]))
    assert visible.status_code == 200, visible.json
    assert visible.json["projection"] == "safe"
    assert visible.json["services"][0]["service"]["id"] == service.id
    nested = client.get(
        f"/api/services/{service.id}/changes", headers=headers(changes["foreign"])
    )
    assert [item["uid"] for item in nested.json["items"]] == [str(change.uid)]


def test_terminal_conflict_and_time_filter_boundaries(client, changes):
    body = {**changes["body"], "event_id": "conflict", "event_type": "change.failed"}
    ingestion.ingest_event(ChangeEventInput.model_validate(body), changes["intake"][3])
    auth = headers(changes["owner"])
    detail = client.get(url(changes), headers=auth).json
    assert detail["lifecycle_conflict"] and detail["status"] == "unknown"
    matching = client.get(
        BASE,
        query_string={
            "occurred_from": body["occurred_at"],
            "occurred_to": body["occurred_at"],
        },
        headers=auth,
    )
    assert matching.json["pagination"]["total"] == 1
    assert (
        client.get(BASE + "?occurred_from=2026-01-01T12:00:01Z", headers=auth).json[
            "pagination"
        ]["total"]
        == 0
    )
    first = client.get(url(changes, "/events?page_size=1"), headers=auth).json
    second = client.get(url(changes, "/events?page_size=1&page=2"), headers=auth).json
    assert first["pagination"]["total"] == 2
    assert first["items"][0]["uid"] != second["items"][0]["uid"]


def test_read_contract_matches_full_safe_and_nested_responses(client, changes):
    from jsonschema import RefResolver
    from openapi_schema_validator import OAS30Validator
    from openapi_spec_validator import validate_spec
    from app.api.openapi.endpoints import changes as contract

    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Changes", "version": "1"},
        "paths": contract.paths(),
        "components": {
            "schemas": contract.components(),
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
        },
    }
    validate_spec(spec)
    resolver = RefResolver.from_schema(spec)
    for role in ("owner", "foreign"):
        for suffix, name in (("", "ChangeRead"), ("/services", "ChangeServicePage")):
            payload = client.get(
                url(changes, suffix), headers=headers(changes[role])
            ).json
            OAS30Validator(
                spec["components"]["schemas"][name], resolver=resolver
            ).validate(payload)
    body = {**changes["body"], "event_id": "conflict", "event_type": "change.failed"}
    ingestion.ingest_event(ChangeEventInput.model_validate(body), changes["intake"][3])
    detail = client.get(url(changes), headers=headers(changes["owner"])).json
    assert detail["diagnostics"][0]["code"] == "terminal_conflict"
    OAS30Validator(
        spec["components"]["schemas"]["ChangeFull"], resolver=resolver
    ).validate(detail)
    events = client.get(url(changes, "/events"), headers=headers(changes["owner"])).json
    OAS30Validator(
        spec["components"]["schemas"]["ChangeEventPage"], resolver=resolver
    ).validate(events)
