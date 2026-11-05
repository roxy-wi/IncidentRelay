"""Cross-surface visibility, durable publication, and independent alert episodes."""

import json
from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo, services_repo
from app.modules.db.models import (
    AlertGroup,
    AlertGroupEpisode,
    Change,
    ChangeIntegration,
    ChangeJob,
    ServiceEvent,
)
from app.services.change_intelligence import timeline
from app.services.change_intelligence.resolver import StaleChangeInputs
from app.services.service_catalog.timeline import (
    list_service_events,
    publish_service_event,
)
from app.settings import Config
from tests.factories import create_group, create_service, create_team, unique
from tests.integrations.test_changes_read import changes, personal, reader
from tests.integrations.test_change_events import intake, setup_identity
from tests.integrations.test_change_integration_groups import headers
from tests.integrations.test_change_correlation import (
    claim_kind,
    edge,
    episode_for,
    run_change,
)
from tests.integrations.test_change_worker import process_resolution

__all__ = ["changes", "intake", "setup_identity"]


def timeline_url(service):
    return f"/api/services/{service.id}/timeline"


def test_safe_publication_is_idempotent_and_never_persists_provider_fields(
    client, changes
):
    change = changes["change"]
    run_change(change, "sync_service_timeline")
    before = list(ServiceEvent.select().dicts())
    assert len(before) == 2
    assert "PRIVATE" not in json.dumps(before, default=str)
    assert all(row["change_event"] and row["change_relation_type"] for row in before)
    with incident_core_repo.write_transaction():
        changes_repo.request_job("sync_service_timeline", change.id)
    run_change(change, "sync_service_timeline")
    assert list(ServiceEvent.select().dicts()) == before
    response = client.get(
        timeline_url(changes["service"]), headers=headers(changes["foreign"])
    )
    assert response.status_code == 200, response.json
    event = response.json["items"][0]
    assert event["payload"] == {
        "change_uid": str(change.uid),
        "kind": change.kind,
        "relation_type": "reported_affected",
    }
    assert "PRIVATE" not in json.dumps(response.json)
    assert event["actor"]["user_id"] is None and event["external_url"] is None
    assert response.headers["Cache-Control"] == "no-store"


def test_publication_and_checkpoint_roll_back_together(changes, monkeypatch):
    change = changes["change"]
    claim = claim_kind("sync_service_timeline", change.id)
    plan = timeline.compute_timeline_batch(claim)
    original = changes_repo.finish_claim

    def fail(*args, **kwargs):
        raise RuntimeError("checkpoint unavailable")

    monkeypatch.setattr(changes_repo, "finish_claim", fail)
    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        timeline.publish_timeline_batch(claim, plan)
    assert ServiceEvent.select().count() == 0
    monkeypatch.setattr(changes_repo, "finish_claim", original)
    timeline.publish_timeline_batch(claim, plan)
    assert ServiceEvent.select().count() == 2


@pytest.mark.parametrize("state", ["pending", "dead"])
def test_unchanged_mapping_keeps_timeline_backoff_and_dead_letter(changes, state):
    change = changes["change"]
    job = ChangeJob.get(ChangeJob.job_type == "sync_service_timeline")
    ChangeJob.update(
        state=state, attempts=3, last_error_class="processing_error"
    ).where(ChangeJob.id == job.id).execute()
    with incident_core_repo.write_transaction():
        changes_repo.request_job("resolve_references", change.id)
    process_resolution(change)
    current = ChangeJob.get_by_id(job.id)
    assert current.state == state and current.attempts == 3
    assert current.last_error_class == "processing_error"
    assert current.requested_generation == job.requested_generation


@pytest.mark.parametrize("changed", ["authority", "graph", "change", "lease"])
def test_stale_or_reclaimed_publication_cannot_write(changes, changed):
    from app.modules.db.models import ChangeGraphState

    change = changes["change"]
    claim = claim_kind("sync_service_timeline", change.id)
    plan = timeline.compute_timeline_batch(claim)
    if changed == "authority":
        ChangeIntegration.update(
            auth_revision=ChangeIntegration.auth_revision + 1
        ).execute()
    elif changed == "graph":
        ChangeGraphState.update(revision=ChangeGraphState.revision + 1).execute()
    elif changed == "change":
        Change.update(revision=Change.revision + 1).execute()
    else:
        ChangeJob.update(lease_expires_at=utc_now() - timedelta(seconds=1)).where(
            ChangeJob.id == claim.id
        ).execute()
        changes_repo.claim_job("replacement")
    with pytest.raises((StaleChangeInputs, changes_repo.LostChangeLease)):
        timeline.publish_timeline_batch(claim, plan)
    assert not ServiceEvent.select().exists()


def test_batch_limit_resumes_without_skipping_or_duplicating(changes, monkeypatch):
    monkeypatch.setattr(Config, "CHANGE_WORKER_BATCH_SIZE", 1)
    change = changes["change"]
    assert run_change(change, "sync_service_timeline").state == "pending"
    assert ServiceEvent.select().count() == 1
    assert run_change(change, "sync_service_timeline").state == "pending"
    assert ServiceEvent.select().count() == 2
    assert run_change(change, "sync_service_timeline").state == "done"
    assert ServiceEvent.select().count() == 2


def test_revocation_filters_before_cursor_limit_and_preserves_legacy_history(
    client, changes
):
    change, service = changes["change"], changes["service"]
    run_change(change, "sync_service_timeline")
    old = publish_service_event(
        service,
        category="integration",
        event_type="legacy",
        title="Legacy event",
        source="legacy",
        occurred_at=utc_now() - timedelta(days=2),
        payload={"original": True},
    )
    ChangeIntegration.update(
        auth_revision=ChangeIntegration.auth_revision + 1
    ).execute()
    response = client.get(
        timeline_url(service) + "?limit=1", headers=headers(changes["foreign"])
    )
    assert [row["id"] for row in response.json["items"]] == [old.id]
    assert response.json["items"][0]["payload"] == {"original": True}
    own_service = changes["intake"][0][2]
    history = client.get(timeline_url(own_service), headers=headers(changes["owner"]))
    assert len(history.json["items"]) == 1
    assert ServiceEvent.select().count() == 3


def test_service_move_hides_derived_history_from_new_reader(client, changes):
    run_change(changes["change"], "sync_service_timeline")
    team = create_team(create_group())
    services_repo.update_service(changes["service"].id, {"team": team.id})
    response = client.get(
        timeline_url(changes["service"]), headers=headers(reader(team))
    )
    assert response.status_code == 200
    assert response.json["items"] == []
    assert list_service_events(changes["service"].id, team_ids=[]) == []


def test_inferred_reader_sees_only_safe_change_and_loses_it_when_graph_changes(
    client, changes
):
    from app.api.schemas.change_events import ChangeEventInput
    from app.modules.db.models import ChangeGraphState
    from app.services.change_intelligence import ingestion

    provider = changes["intake"][0][2]
    consumer = create_service(create_team(create_group()))
    edge(provider, consumer, correlation_enabled=True)
    ingestion.ingest_event(
        ChangeEventInput.model_validate(
            {
                **changes["body"],
                "event_id": "recent-event",
                "occurred_at": utc_now().isoformat() + "Z",
            }
        ),
        changes["intake"][3],
    )
    # Catalog edits invalidate both mapping and impact projections.
    with incident_core_repo.write_transaction():
        changes_repo.request_job("resolve_references", changes["change"].id)
    process_resolution(changes["change"])
    run_change(changes["change"])
    run_change(changes["change"], "sync_service_timeline")
    auth = headers(reader(consumer.team))
    response = client.get(f"/api/services/{consumer.id}/changes", headers=auth)
    assert response.status_code == 200, response.json
    assert response.json["pagination"]["total"] == 1
    assert (
        response.json["items"][0]["services"][0]["relation_type"] == "inferred_impact"
    )
    assert "PRIVATE" not in json.dumps(response.json)
    linked = client.get(f"/api/changes/{changes['change'].uid}/services", headers=auth)
    assert linked.status_code == 200, linked.json
    assert linked.json["pagination"]["total"] == 1
    assert linked.json["items"][0]["relation_type"] == "inferred_impact"
    events = client.get(timeline_url(consumer), headers=auth).json["items"]
    assert (
        len(events) == 2 and events[0]["payload"]["relation_type"] == "inferred_impact"
    )
    ChangeGraphState.update(revision=ChangeGraphState.revision + 1).execute()
    assert client.get(timeline_url(consumer), headers=auth).json["items"] == []
    assert (
        client.get(f"/api/changes/{changes['change'].uid}", headers=auth).status_code
        == 404
    )


def test_related_changes_use_only_selected_episode_and_never_reconstruct_legacy(
    client, changes
):
    service = changes["service"]
    first = episode_for(service)
    auth = headers(changes["foreign"])
    group_url = f"/api/alert-groups/{first.alert_group_id}"
    from app.modules.db.models import ChangeAlertGroupCorrelation

    ChangeAlertGroupCorrelation.create(
        change=changes["change"],
        episode=first,
        score=None,
        reason="manual",
        engine_version="manual",
    )
    AlertGroupEpisode.update(state="resolved", ended_at=utc_now()).where(
        AlertGroupEpisode.id == first.id
    ).execute()
    second = AlertGroupEpisode.create(
        alert_group=first.alert_group_id,
        ordinal=2,
        started_at=utc_now(),
        state="open",
        start_quality="exact",
    )
    selected = client.get(group_url + "/related-changes", headers=auth)
    assert selected.status_code == 200, selected.json
    assert selected.json["episode"]["id"] == second.id
    assert selected.json["pagination"]["total"] == 0
    previous = client.get(
        group_url + f"/related-changes?episode_id={first.id}", headers=auth
    )
    assert previous.json["pagination"]["total"] == 1
    assert "PRIVATE" not in json.dumps(previous.json)
    another = episode_for(service)
    assert (
        client.get(
            group_url + f"/related-changes?episode_id={another.id}", headers=auth
        ).status_code
        == 404
    )
    episodes = client.get(group_url + "/episodes?page_size=1", headers=auth).json
    assert (
        episodes["pagination"]["total"] == 2 and episodes["items"][0]["id"] == second.id
    )
    legacy = AlertGroup.create(
        team=service.team_id,
        title="Legacy",
        source="test",
        group_key=unique("legacy"),
        group_key_hash=unique("legacy"),
    )
    count = AlertGroupEpisode.select().count()
    result = client.get(f"/api/alert-groups/{legacy.id}/related-changes", headers=auth)
    assert result.json["episode"] is None and result.json["eligibility"] == "no_episode"
    assert AlertGroupEpisode.select().count() == count


def test_personal_tokens_need_change_scope_on_each_surface(client, changes):
    service, user = changes["service"], changes["foreign"]
    episode = episode_for(service)
    run_change(changes["change"], "sync_service_timeline")
    group_url = f"/api/alert-groups/{episode.alert_group_id}"
    for suffix in ("/episodes", "/related-changes"):
        assert (
            client.get(
                group_url + suffix, headers=personal(user, ["alerts:read"])
            ).status_code
            == 403
        )
        assert (
            client.get(
                group_url + suffix, headers=personal(user, ["changes:read"])
            ).status_code
            == 403
        )
        assert (
            client.get(
                group_url + suffix,
                headers=personal(user, ["changes:read", "alerts:read"]),
            ).status_code
            == 200
        )
    scoped = personal(user, ["services:read"])
    assert client.get(timeline_url(service), headers=scoped).json["items"] == []
    scoped = personal(user, ["services:read", "changes:read"])
    assert len(client.get(timeline_url(service), headers=scoped).json["items"]) == 1
    restricted = personal(
        changes["owner"],
        ["services:read", "changes:read"],
        team_id=changes["intake"][0][2].team_id,
    )
    assert client.get(timeline_url(service), headers=restricted).status_code == 403


def test_alert_projection_matches_contract_and_rejects_unrelated_episode(
    client, changes
):
    from openapi_schema_validator import OAS30Validator
    from app.api.openapi.spec import build_openapi_spec
    from app.modules.db.models import ChangeAlertGroupCorrelation

    episode = episode_for(changes["service"])
    ChangeAlertGroupCorrelation.create(
        change=changes["change"],
        episode=episode,
        score=None,
        reason="manual",
        engine_version="manual",
    )
    url = f"/api/alert-groups/{episode.alert_group_id}"
    spec = build_openapi_spec()
    for suffix, schema in (
        ("/episodes", "AlertEpisodePage"),
        ("/related-changes", "AlertRelatedChangesPage"),
    ):
        response = client.get(url + suffix, headers=headers(changes["foreign"]))
        assert response.status_code == 200
        OAS30Validator(
            {
                "$ref": "#/components/schemas/" + schema,
                "components": spec["components"],
            },
            format_checker=OAS30Validator.FORMAT_CHECKER,
        ).validate(response.json)
    hidden = client.get(url + "/related-changes", headers=headers(changes["owner"]))
    assert hidden.status_code == 404
    for query in ("episode_id=0", "episode_id=1&episode_id=2", "private=yes"):
        assert (
            client.get(
                url + "/related-changes?" + query, headers=headers(changes["foreign"])
            ).status_code
            == 400
        )
    ChangeIntegration.update(
        auth_revision=ChangeIntegration.auth_revision + 1
    ).execute()
    response = client.get(
        url + "/related-changes?page_size=1", headers=headers(changes["foreign"])
    )
    assert response.json["pagination"]["total"] == 0 and response.json["items"] == []
