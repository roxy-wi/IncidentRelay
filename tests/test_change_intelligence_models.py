"""Storage contracts shared by PostgreSQL and SQLite."""

import threading
import uuid
from datetime import datetime, timedelta

import pytest
from peewee import IntegrityError, SqliteDatabase

from app.modules.db.changes_repo import request_job
from app.modules.db.models import (
    AlertGroup,
    AlertGroupEpisode,
    ApiToken,
    Change,
    ChangeEvent,
    ChangeGrant,
    ChangeGraphState,
    ChangeIntegration,
    ChangeJob,
    ChangeService,
    ChangeServiceReference,
    ChangeSource,
    Service,
)
from tests.factories import create_group, create_team, create_user, unique


@pytest.fixture
def context(db):
    team = create_team(create_group())
    integration = ChangeIntegration.create(name="Central CI")
    source = ChangeSource.create(
        integration=integration, owner_team=team, source="deploy"
    )
    change = Change.create(
        source=source,
        integration=integration,
        owner_team=team,
        external_change_id="run-1",
        kind="deployment",
        title="Release",
    )
    event = ChangeEvent.create(
        change=change,
        source=source,
        integration=integration,
        external_event_id="event-1",
        event_type="change.started",
        occurred_at=datetime(2026, 10, 1),
        request_digest="a" * 64,
    )
    return team, integration, source, change, event


def _event(source, change, **overrides):
    values = dict(
        change=change,
        source=source,
        integration=source.integration_id,
        external_event_id=unique("event"),
        event_type="change.updated",
        occurred_at=datetime(2026, 10, 1),
        request_digest="b" * 64,
    )
    return ChangeEvent.create(**(values | overrides))


def _reference(team, change, event, **overrides):
    values = dict(
        change=change,
        first_event=event,
        relation_type="changed",
        ref_type="slug",
        namespace_team=team,
        requested_service_slug="api",
        normalized_ref_key=f"slug:team-id:{team.id}/api",
    )
    return ChangeServiceReference.create(**(values | overrides))


def _invalid(db, write):
    # A savepoint keeps the PostgreSQL connection usable after a constraint error.
    with pytest.raises(IntegrityError), db.atomic():
        write()


def test_source_namespace_survives_disabling_integration(db, context):
    team, integration, source, _, _ = context
    integration.active = False
    integration.save()
    other = ChangeIntegration.create(name="Other CI")
    _invalid(
        db,
        lambda: ChangeSource.create(
            integration=other, owner_team=team, source=source.source
        ),
    )
    assert ChangeSource.get_by_id(source.id).integration_id == integration.id


def test_event_identity_and_nullable_sequence_uniqueness(db, context):
    team, integration, source, change, first = context
    other = Change.create(
        source=source,
        integration=integration,
        owner_team=team,
        external_change_id="run-2",
        kind="deployment",
        title="Other release",
    )
    _invalid(
        db, lambda: _event(source, other, external_event_id=first.external_event_id)
    )
    _event(source, change)
    _event(source, change)  # Timestamp mode can have several NULL sequences.
    _event(source, change, source_sequence=0)
    _invalid(db, lambda: _event(source, change, source_sequence=0))
    _invalid(db, lambda: _event(source, change, source_sequence=-1))
    _event(source, other, source_sequence=0)


def test_source_change_event_identity_cannot_be_mixed(db, context):
    team, integration, source, change, _ = context
    other_team = create_team(team.group)
    other_source = ChangeSource.create(
        integration=integration, owner_team=other_team, source="deploy"
    )
    _invalid(
        db,
        lambda: Change.create(
            source=source,
            integration=integration,
            owner_team=other_team,
            external_change_id="wrong",
            kind="deployment",
            title="Wrong owner",
        ),
    )
    _invalid(db, lambda: _event(other_source, change))
    _invalid(db, lambda: _event(source, 99999999))


def test_team_and_service_grants_have_normalized_unique_keys(db, context):
    team, _, source, _, _ = context
    values = dict(
        source=source,
        target_team=team,
        capability="changed",
        target_key=f"team:{team.id}",
    )
    ChangeGrant.create(**values)
    _invalid(db, lambda: ChangeGrant.create(**values))
    _invalid(db, lambda: ChangeGrant.create(**(values | {"target_key": "team:other"})))
    service = Service.create(team=team, name="API", slug="api")
    values.update(target_service=service, target_key=f"service:{service.id}")
    ChangeGrant.create(**values)
    _invalid(db, lambda: ChangeGrant.create(**values))


def test_reference_namespace_identity_and_canonical_deduplication(db, context):
    team, _, _, change, event = context
    reference = _reference(team, change, event)
    _invalid(db, lambda: _reference(team, change, event))
    _invalid(db, lambda: _reference(team, change, event, namespace_team=None))
    _invalid(
        db,
        lambda: _reference(team, change, event, normalized_ref_key="slug:old-team/api"),
    )
    _invalid(db, lambda: _reference(team, change, event, requested_service_id=10))
    team.slug = unique("renamed")
    team.save()
    assert ChangeServiceReference.get_by_id(reference.id).namespace_team_id == team.id
    service = Service.create(team=team, name="API", slug="api")
    canonical = dict(
        change=change,
        service=service,
        relation_type="changed",
        first_reference=reference,
    )
    _invalid(db, lambda: ChangeService.create(**canonical))
    reference.resolved_service = service
    reference.resolution_status = "resolved"
    reference.save()
    ChangeService.create(**canonical)
    _invalid(db, lambda: ChangeService.create(**canonical))
    _invalid(
        db,
        lambda: ChangeService.create(
            **(canonical | {"relation_type": "reported_affected"})
        ),
    )


def test_reference_cannot_use_another_changes_event(db, context):
    team, integration, source, change, event = context
    other = Change.create(
        source=source,
        integration=integration,
        owner_team=team,
        external_change_id="run-2",
        kind="deployment",
        title="Other",
    )
    _invalid(db, lambda: _reference(team, other, event))
    _invalid(db, lambda: _reference(team, change, event, resolution_status="resolved"))


def test_token_deletion_keeps_event_identity_and_rejects_mixed_principals(db, context):
    team, integration, _, _, event = context
    user = create_user(group=team.group)
    values = dict(
        name="CI",
        token_prefix="prefix",
        token_hash=unique("hash"),
        change_integration=integration,
    )
    for field, value in (("user", user), ("group", team.group), ("team", team)):
        _invalid(
            db,
            lambda field=field, value=value: ApiToken.create(
                **(values | {field: value})
            ),
        )
    token = ApiToken.create(**values, scopes=["changes:ingest"])
    event.ingest_token = token
    event.save()
    token.delete_instance()
    saved = ChangeEvent.get_by_id(event.id)
    assert saved.ingest_token_id is None
    assert saved.integration_id == integration.id
    assert saved.request_digest == "a" * 64


def test_history_cannot_disappear_by_deleting_owner_or_source(db, context):
    team, integration, source, change, event = context
    for row in (team, integration, source, change):
        _invalid(db, row.delete_instance)
    assert ChangeEvent.get_by_id(event.id).change_id == change.id


def test_episode_constraints_and_current_pointer_foreign_key(db, context):
    team, _, _, _, _ = context
    group = AlertGroup.create(
        team=team, source="test", title="Test", group_key="a", group_key_hash="a"
    )
    episode = AlertGroupEpisode.create(alert_group=group, ordinal=1)
    group.current_episode = episode
    group.save()
    _invalid(db, lambda: AlertGroupEpisode.create(alert_group=group, ordinal=2))
    _invalid(
        db,
        lambda: AlertGroupEpisode.create(
            alert_group=group, ordinal=0, state="resolved"
        ),
    )
    _invalid(
        db,
        lambda: AlertGroupEpisode.create(
            alert_group=group, ordinal=2, state="resolved", start_quality="exact"
        ),
    )
    _invalid(
        db,
        lambda: (
            AlertGroup.update(current_episode=99999999)
            .where(AlertGroup.id == group.id)
            .execute()
        ),
    )
    episode.state = "resolved"
    episode.save()
    second = AlertGroupEpisode.create(alert_group=group, ordinal=2)
    _invalid(
        db,
        lambda: AlertGroupEpisode.create(
            alert_group=group, ordinal=2, state="resolved"
        ),
    )
    episode.delete_instance()
    assert AlertGroup.get_by_id(group.id).current_episode_id is None
    group.delete_instance()
    assert (
        not AlertGroupEpisode.select().where(AlertGroupEpisode.id == second.id).exists()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "invalid"),
        ("status", "invalid"),
        ("revision", 0),
        ("ordering_mode", "mixed"),
        ("mapping_status", "invalid"),
    ],
)
def test_invalid_projection_values_are_rejected(db, context, field, value):
    change = context[3]
    _invalid(
        db,
        lambda: Change.update(**{field: value}).where(Change.id == change.id).execute(),
    )


def test_graph_revision_is_a_positive_singleton(db):
    assert ChangeGraphState.get_by_id(1).revision >= 1
    _invalid(db, lambda: ChangeGraphState.create(id=2))
    _invalid(db, lambda: ChangeGraphState.update(revision=0).execute())


def test_job_request_requires_caller_transaction_and_rolls_back(db, context):
    change = context[3]
    with pytest.raises(RuntimeError, match="caller.*transaction"):
        request_job("resolve_references", change.id)
    with pytest.raises(RuntimeError, match="injected"), db.atomic():
        Change.update(title="Rolled back").where(Change.id == change.id).execute()
        request_job("resolve_references", change.id)
        raise RuntimeError("injected")
    assert ChangeJob.select().count() == 0
    assert Change.get_by_id(change.id).title == "Release"


def test_repeated_job_request_preserves_running_lease_and_new_generation(db, context):
    change = context[3]
    with db.atomic():
        job = request_job("resolve_references", change.id, target_revision=3)
    token = uuid.uuid4()
    expires = datetime(2026, 10, 28) + timedelta(minutes=5)
    ChangeJob.update(
        state="running",
        claimed_generation=1,
        lease_token=token,
        lease_owner="worker-A",
        lease_expires_at=expires,
        attempts=2,
    ).where(ChangeJob.id == job.id).execute()
    with db.atomic():
        updated = request_job("resolve_references", change.id, target_revision=2)
    assert updated.id == job.id
    assert updated.requested_generation == 2
    assert updated.claimed_generation == 1
    assert updated.target_revision == 3
    assert updated.state == "running" and updated.attempts == 2
    assert updated.lease_token == token and updated.lease_expires_at == expires


def test_job_reschedule_rollback_preserves_previous_generation(db, context):
    change_id = context[3].id
    with db.atomic():
        job = request_job("resolve_references", change_id)
    with pytest.raises(RuntimeError), db.atomic():
        request_job("resolve_references", change_id, target_revision=10)
        raise RuntimeError("domain mutation failed")
    saved = ChangeJob.get_by_id(job.id)
    assert saved.requested_generation == 1 and saved.target_revision == 0


def test_dead_job_request_starts_new_generation_without_stale_lease(db, context):
    job = ChangeJob.create(
        job_type="resolve_references",
        entity_id=context[3].id,
        state="dead",
        attempts=5,
        last_error_class="temporary_failure",
        lease_owner="old",
        lease_token=uuid.uuid4(),
        claimed_generation=1,
        lease_expires_at=datetime(2026, 1, 1),
        cursor={"after_id": 100},
    )
    with db.atomic():
        updated = request_job(job.job_type, job.entity_id)
    assert updated.requested_generation == 2
    assert updated.state == "pending" and updated.attempts == 0
    assert updated.lease_token is None and updated.lease_owner is None
    assert updated.lease_expires_at is None
    assert updated.cursor is None and updated.last_error_class is None


def test_concurrent_job_requests_coalesce_without_losing_generation(db, context):
    change_id = context[3].id
    barrier = threading.Barrier(2)
    errors = []

    def enqueue():
        try:
            with db.connection_context():
                barrier.wait(timeout=10)
                transaction = (
                    db.atomic("IMMEDIATE")
                    if isinstance(db, SqliteDatabase)
                    else db.atomic()
                )
                with transaction:
                    request_job("resolve_references", change_id)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=enqueue) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    job = ChangeJob.get()
    assert job.requested_generation == 2 and job.state == "pending"


@pytest.mark.parametrize(
    "values",
    [
        {"entity_id": 0},
        {"job_type": "unknown"},
        {"requested_generation": 0},
        {"claimed_generation": 2},
        {"completed_generation": 1},
        {"state": "running"},
    ],
)
def test_invalid_job_state_is_rejected(db, values):
    _invalid(
        db,
        lambda: ChangeJob.create(
            **({"job_type": "discover_graph", "entity_id": 1} | values)
        ),
    )
