"""Durable processing, stale inputs, recovery, and administrative boundaries."""

from datetime import timedelta

import pytest
from peewee import OperationalError

from app.api.schemas.change_events import ChangeEventInput
from app.api.schemas.change_integrations import GrantUpdate, SourceUpdate
from app.modules.common import utc_now
from app.modules.db import (
    changes_repo as queue,
    incident_core_repo,
    services_repo,
    teams_repo,
)
from app.modules.db.models import (
    ApiToken,
    AuditLog,
    Change,
    ChangeEvent,
    ChangeGraphState,
    ChangeJob,
    SystemSettings,
    ChangeService,
    ChangeServiceReference,
    Service,
)
from app.services.change_intelligence import (
    administration as admin,
    ingestion,
    job_administration,
    resolver,
    worker,
)
from app.services.change_intelligence.catalog import graph_change
from app.settings import Config
from tests.factories import create_group, create_service, create_team
from tests.integrations.test_change_events import event_payload, intake, setup_identity
from tests.integrations.test_change_integration_groups import headers, owned_identity
from tests.integrations.test_change_integrations import (
    BASE,
    credential,
    grant,
    revision,
)

__all__ = ["intake", "setup_identity", "owned_identity"]


def pending_change(intake, *, slugs=None, change_id="build-1"):
    payload = event_payload(intake[0], change_id=change_id, event_id=change_id)
    payload.pop("changed_service_ids")
    payload["changed_services"] = [
        {"service_slug": slug} for slug in (slugs or ["late-service"])
    ]
    ingestion.ingest_event(ChangeEventInput.model_validate(payload), intake[3])
    return Change.get(Change.external_change_id == change_id)


def claim_resolution(change):
    job = ChangeJob.get(
        ChangeJob.job_type == "resolve_references", ChangeJob.entity_id == change.id
    )
    ChangeJob.update(next_attempt_at=utc_now() + timedelta(hours=1)).where(
        ChangeJob.id != job.id
    ).execute()
    ChangeJob.update(next_attempt_at=utc_now() - timedelta(seconds=1)).where(
        ChangeJob.id == job.id
    ).execute()
    return queue.claim_job("test-worker")


def process_resolution(change):
    claim = claim_resolution(change)
    assert claim is not None
    assert worker.process_claim(claim) == "processed"
    return ChangeJob.get_by_id(claim.id)


def test_late_mapping_survives_credential_revocation(intake):
    change = pending_change(intake)
    before = ChangeEvent.get().request_snapshot
    ApiToken.update(active=False).where(ApiToken.id == intake[2].id).execute()
    service = create_service(intake[0][2].team, slug="late-service")
    job = process_resolution(change)
    ref = ChangeServiceReference.get()
    assert ref.resolved_service_id == service.id
    assert ref.resolution_status == "resolved" and ref.verification_state == "trusted"
    assert ChangeService.get().service_id == service.id
    assert ChangeEvent.get().request_snapshot == before
    assert job.state == "done" and job.completed_generation == job.requested_generation
    assert Change.get().revision == change.revision + 1


def test_pending_waits_then_expires_without_busy_loop(intake):
    change = pending_change(intake)
    job = process_resolution(change)
    assert job.state == "pending" and job.next_attempt_at > utc_now()
    assert ChangeServiceReference.get().resolution_status == "pending_resolution"
    assert queue.claim_job("other") is None
    ChangeServiceReference.update(expires_at=utc_now() - timedelta(seconds=1)).execute()
    job = process_resolution(change)
    assert job.state == "done"
    assert ChangeServiceReference.get().resolution_status == "expired"
    assert ChangeServiceReference.get().last_error_code == "pending_ttl_expired"
    assert ChangeService.select().count() == 0


def test_legacy_pending_without_expiry_uses_acceptance_time(intake):
    change = pending_change(intake)
    ChangeServiceReference.update(
        expires_at=None, created_at=utc_now() - timedelta(days=8)
    ).execute()
    process_resolution(change)
    assert ChangeServiceReference.get().resolution_status == "expired"


def test_new_event_rechecks_denied_reference_under_restored_grant(intake):
    identity, permission, _, raw = intake
    integration, source, service, actor = identity
    payload = event_payload(identity)
    ingestion.ingest_event(ChangeEventInput.model_validate(payload), raw)
    for active in (False, True):
        admin.update_grant(
            integration.id,
            source.id,
            permission.id,
            GrantUpdate(expected_revision=revision(integration), active=active),
            actor_id=actor.id,
        )
        with incident_core_repo.write_transaction():
            queue.request_job("resolve_references", Change.get().id)
        process_resolution(Change.get())
        assert ChangeServiceReference.get().resolution_status == "denied"
    before = ChangeServiceReference.get()
    payload["event_id"] = "explicit-retry"
    _, created = ingestion.ingest_event(ChangeEventInput.model_validate(payload), raw)
    assert created
    ref = ChangeServiceReference.get()
    assert ref.resolution_status == "resolved" and ref.last_error_code is None
    assert ref.resolved_service_id == service.id
    assert ref.first_event_id == before.first_event_id
    process_resolution(Change.get())
    assert ChangeService.get().verification_state == "trusted"


@pytest.mark.parametrize("blocked", ["expired", "denied", "invalid"])
def test_new_event_restarts_pending_window_but_duplicate_is_side_effect_free(
    client, intake, blocked
):
    change = pending_change(intake)
    ChangeServiceReference.update(
        resolution_status=blocked,
        verification_state="rejected",
        expires_at=utc_now() - timedelta(seconds=1),
        last_error_code="previous_failure",
    ).execute()
    before = ChangeServiceReference.get()
    job_before = ChangeJob.get(ChangeJob.job_type == "resolve_references")
    payload = event_payload(intake[0], event_id="build-1")
    payload.pop("changed_service_ids")
    payload["changed_services"] = [{"service_slug": "late-service"}]
    request_headers = {"Authorization": f"Bearer {intake[3]}"}
    duplicate = client.post("/api/change-events", json=payload, headers=request_headers)
    assert duplicate.status_code == 200
    assert ChangeServiceReference.get().__data__ == before.__data__
    assert ChangeJob.get_by_id(job_before.id).__data__ == job_before.__data__
    assert Change.get().revision == change.revision
    payload["event_id"] = "explicit-retry"
    response = client.post("/api/change-events", json=payload, headers=request_headers)
    assert response.status_code == 201, response.json
    ref = ChangeServiceReference.get()
    assert ref.resolution_status == "pending_resolution"
    assert ref.last_error_code is None and ref.expires_at > utc_now()
    assert ref.namespace_team_id == before.namespace_team_id
    assert ref.first_event_id == before.first_event_id
    assert ChangeJob.get_by_id(job_before.id).requested_generation == (
        job_before.requested_generation + 1
    )


def test_new_event_retry_keeps_resolved_identity_after_slug_reuse(intake):
    change = pending_change(intake)
    service = create_service(intake[0][2].team, slug="late-service")
    process_resolution(change)
    services_repo.update_service(service.id, {"slug": "renamed-service"})
    replacement = create_service(service.team, slug="late-service")
    ChangeServiceReference.update(
        resolution_status="denied", verification_state="rejected"
    ).execute()
    payload = event_payload(intake[0], event_id="retry-pinned")
    payload.pop("changed_service_ids")
    payload["changed_services"] = [{"service_slug": "late-service"}]
    ingestion.ingest_event(ChangeEventInput.model_validate(payload), intake[3])
    ref = ChangeServiceReference.get()
    assert ref.resolution_status == "resolved"
    assert ref.resolved_service_id == service.id
    assert (
        not ChangeService.select()
        .where(ChangeService.service == replacement.id)
        .exists()
    )


def test_team_rename_and_slug_reuse_keep_numeric_namespace(intake):
    change = pending_change(intake)
    team = intake[0][2].team
    old_slug = team.slug
    teams_repo.update_team(team.id, {"slug": "renamed-team"})
    other = create_team(create_group(), slug=old_slug)
    create_service(other, slug="late-service")
    process_resolution(change)
    assert ChangeService.select().count() == 0
    correct = create_service(team, slug="late-service")
    process_resolution(change)
    assert ChangeService.get().service_id == correct.id
    assert ChangeServiceReference.get().namespace_team_id == team.id


def test_resolved_service_move_never_rebinds_to_slug_replacement(intake):
    payload = ChangeEventInput.model_validate(event_payload(intake[0]))
    ingestion.ingest_event(payload, intake[3])
    change = Change.get()
    service = intake[0][2]
    other = create_team(create_group())
    services_repo.update_service(service.id, {"team": other.id})
    create_service(service.team, slug=service.slug)
    process_resolution(change)
    ref = ChangeServiceReference.get()
    assert ref.resolved_service_id == service.id
    assert ref.resolution_status == "invalid"
    assert ChangeService.get().verification_state == "rejected"


def test_expired_lease_cannot_publish_renew_ack_or_retry_replacement(intake):
    change = pending_change(intake)
    first = claim_resolution(change)
    ChangeJob.update(lease_expires_at=utc_now() - timedelta(seconds=1)).where(
        ChangeJob.id == first.id
    ).execute()
    second = queue.claim_job("replacement")
    assert second.id == first.id and second.lease_token != first.lease_token
    with pytest.raises(queue.LostChangeLease):
        queue.renew_lease(first)
    with pytest.raises(queue.LostChangeLease), incident_core_repo.write_transaction():
        queue.finish_claim(first)
    assert not queue.fail_claim(first, transient=True)
    assert not queue.release_stale_claim(first)
    assert ChangeJob.get_by_id(first.id).lease_token == second.lease_token


def test_new_trigger_during_calculation_survives_stale_worker(intake):
    change = pending_change(intake)
    create_service(intake[0][2].team, slug="late-service")
    claim = claim_resolution(change)
    plan = resolver.compute_reference_batch(claim)
    payload = event_payload(intake[0], event_id="newer")
    ingestion.ingest_event(ChangeEventInput.model_validate(payload), intake[3])
    with pytest.raises(resolver.StaleChangeInputs):
        resolver.publish_reference_batch(claim, plan)
    assert queue.release_stale_claim(claim)
    job = ChangeJob.get_by_id(claim.id)
    assert job.requested_generation == claim.claimed_generation + 1
    assert job.state == "pending"
    process_resolution(change)
    assert ChangeService.select().count() == 2


@pytest.mark.parametrize("change_input", ["grant", "source", "graph"])
def test_input_change_between_compute_and_publish_discards_result(intake, change_input):
    change = pending_change(intake)
    create_service(intake[0][2].team, slug="late-service")
    claim = claim_resolution(change)
    plan = resolver.compute_reference_batch(claim)
    identity, permission, _, _ = intake
    integration, source, _, actor = identity
    if change_input == "grant":
        admin.update_grant(
            integration.id,
            source.id,
            permission.id,
            GrantUpdate(expected_revision=revision(integration), active=False),
            actor_id=actor.id,
        )
    elif change_input == "source":
        admin.update_source(
            integration.id,
            source.id,
            SourceUpdate(expected_revision=revision(integration), active=False),
            actor_id=actor.id,
        )
    else:
        with graph_change():
            pass
    with pytest.raises(resolver.StaleChangeInputs):
        resolver.publish_reference_batch(claim, plan)
    assert ChangeService.select().count() == 0
    queue.release_stale_claim(claim)
    process_resolution(change)
    assert ChangeServiceReference.get().resolution_status == (
        "resolved" if change_input == "graph" else "denied"
    )


def test_failure_after_publication_before_ack_rolls_back(intake, monkeypatch):
    change = pending_change(intake)
    create_service(intake[0][2].team, slug="late-service")
    claim = claim_resolution(change)
    original = queue.finish_claim

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected crash")

    with monkeypatch.context() as patch:
        patch.setattr(queue, "finish_claim", crash)
        assert worker.process_claim(claim) == "failed"
    assert ChangeService.select().count() == 0
    assert ChangeServiceReference.get().resolution_status == "pending_resolution"
    assert Change.get().revision == change.revision
    assert ChangeJob.get_by_id(claim.id).state == "dead"


def test_transient_failure_backoff_exhaustion_and_crash_budget(intake, monkeypatch):
    change = pending_change(intake)
    SystemSettings.update(change_worker_max_attempts=2).execute()
    error = OperationalError("parameters must never be logged")
    error.__cause__ = Exception()
    error.__cause__.pgcode = "40001"

    def unavailable(_claim):
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(worker, "compute_reference_batch", unavailable)
        first = claim_resolution(change)
        assert worker.process_claim(first) == "failed"
        job = ChangeJob.get_by_id(first.id)
        assert job.state == "pending" and job.next_attempt_at > utc_now()
        second = claim_resolution(change)
        assert worker.process_claim(second) == "failed"
    assert ChangeJob.get_by_id(first.id).state == "dead"
    ChangeJob.update(state="pending", attempts=0, next_attempt_at=utc_now()).where(
        ChangeJob.id == first.id
    ).execute()
    first = queue.claim_job("crash-1")
    ChangeJob.update(lease_expires_at=utc_now() - timedelta(seconds=1)).where(
        ChangeJob.id == first.id
    ).execute()
    second = queue.claim_job("crash-2")
    ChangeJob.update(lease_expires_at=utc_now() - timedelta(seconds=1)).where(
        ChangeJob.id == second.id
    ).execute()
    assert queue.claim_job("third") is None
    assert ChangeJob.get_by_id(first.id).last_error_class == "attempts_exhausted"


def test_batched_resolver_resumes_and_publishes_final_stamps(intake):
    SystemSettings.update(change_worker_batch_size=1).execute()
    change = pending_change(intake, slugs=["one", "two", "three"])
    for slug in ["one", "two", "three"]:
        create_service(intake[0][2].team, slug=slug)
    first = process_resolution(change)
    assert first.cursor["after_id"] > 0 and first.state == "pending"
    second = process_resolution(change)
    assert second.cursor["after_id"] > first.cursor["after_id"]
    third = process_resolution(change)
    assert third.state == "done" and third.cursor is None
    assert ChangeService.select().count() == 3
    for link in ChangeService.select():
        assert link.input_stamp["change_revision"] == Change.get().revision


def test_audited_retry_revives_expired_reference_and_rejects_stale_generation(
    client, intake, admin_headers
):
    change = pending_change(intake)
    ChangeServiceReference.update(expires_at=utc_now() - timedelta(seconds=1)).execute()
    job = process_resolution(change)
    original = ChangeEvent.get().request_snapshot
    create_service(intake[0][2].team, slug="late-service")
    with incident_core_repo.write_transaction():
        queue.request_job("resolve_references", change.id)
    job = process_resolution(change)
    assert ChangeServiceReference.get().resolution_status == "expired"
    url = f"{BASE}/{intake[0][0].id}/jobs/{job.id}/retry"
    response = client.post(
        url,
        json={"expected_generation": job.requested_generation},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.json
    assert (
        client.post(
            url,
            json={"expected_generation": job.requested_generation},
            headers=admin_headers,
        ).status_code
        == 409
    )
    assert (
        AuditLog.select()
        .where(AuditLog.action == "change_integration.job_retried")
        .exists()
    )
    process_resolution(change)
    assert ChangeServiceReference.get().resolution_status == "resolved"
    assert ChangeEvent.get().request_snapshot == original


def test_group_admin_job_access_stays_in_owned_integration(
    client, owned_identity, setup_identity
):
    grant(owned_identity)
    _, raw = credential(owned_identity)
    ingestion.ingest_event(
        ChangeEventInput.model_validate(event_payload(owned_identity)), raw
    )
    owned = ChangeJob.get(ChangeJob.job_type == "resolve_references")
    group_headers = headers(owned_identity[3])
    listed = client.get(f"{BASE}/{owned_identity[0].id}/jobs", headers=group_headers)
    assert listed.status_code == 200
    assert owned.id in [job["id"] for job in listed.json["items"]]
    assert "entity_id" not in listed.json["items"][0]
    assert client.get(f"{BASE}/jobs", headers=group_headers).status_code == 403
    assert (
        client.post(
            f"{BASE}/jobs/{owned.id}/retry",
            json={"expected_generation": owned.requested_generation},
            headers=group_headers,
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"{BASE}/{setup_identity[0].id}/jobs", headers=group_headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{BASE}/{owned_identity[0].id}/jobs/{owned.id}/retry",
            json={"expected_generation": owned.requested_generation},
            headers=group_headers,
        ).status_code
        == 200
    )


def test_timeline_job_for_missing_change_finishes_without_looping(intake):
    ChangeJob.delete().execute()
    with incident_core_repo.write_transaction():
        queue.request_job("sync_service_timeline", 1)
    assert worker.process_change_jobs() == 1
    job = ChangeJob.get(ChangeJob.job_type == "sync_service_timeline")
    assert job.state == "done" and job.last_error_class == "entity_missing"
    assert worker.process_change_jobs() == 0


def test_catalog_mutation_and_queue_failure_roll_back_together(intake, monkeypatch):
    service = intake[0][2]
    before = ChangeGraphState.get_by_id(1).revision

    def fail(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(queue, "request_job", fail)
        with pytest.raises(RuntimeError):
            services_repo.update_service(service.id, {"name": "must roll back"})
    assert Service.get_by_id(service.id).name == service.name
    assert ChangeGraphState.get_by_id(1).revision == before


def test_queue_metrics_only_expose_fixed_categories(intake):
    from app.services.change_intelligence.metrics import change_worker_gauges

    pending_change(intake)
    samples = [sample for family in change_worker_gauges() for sample in family.samples]
    assert any(sample.name == "incidentrelay_change_jobs" for sample in samples)
    assert all(
        set(sample.labels) <= {"state", "job_type", "error_class"} for sample in samples
    )


def test_queue_metrics_survive_database_init_failure_without_logging_secrets(
    monkeypatch, caplog
):
    from app.services.change_intelligence import metrics

    def fail():
        raise OperationalError("sensitive connection parameters")

    monkeypatch.setattr(metrics, "init_database", fail)
    assert list(metrics.change_worker_gauges()) == []
    assert "OperationalError" in caplog.text
    assert "sensitive connection parameters" not in caplog.text


def test_worker_counters_respect_metrics_switch(monkeypatch):
    from app.services import metrics

    counter = metrics.CHANGE_WORKER_RESULTS.labels(outcome="processed")
    before = counter._value.get()
    monkeypatch.setattr(Config, "METRICS_ENABLED", False)
    metrics.record_change_worker_result("processed")
    assert counter._value.get() == before
    monkeypatch.setattr(Config, "METRICS_ENABLED", True)
    metrics.record_change_worker_result("processed")
    assert counter._value.get() == before + 1
    with pytest.raises(ValueError):
        metrics.record_change_worker_result("sender-defined-label")


def test_discovery_cursor_survives_retry_and_requests_each_change(intake):
    SystemSettings.update(change_worker_batch_size=1).execute()
    changes = [pending_change(intake, change_id=f"build-{index}") for index in range(3)]
    ChangeJob.delete().execute()
    with incident_core_repo.write_transaction():
        discovery = queue.request_job("discover_auth", intake[0][0].id)
    first = queue.claim_job("sweep-first")
    plan = worker.compute_discovery_batch(first)
    worker.publish_discovery_batch(first, plan)
    checkpoint = ChangeJob.get_by_id(discovery.id).cursor
    assert checkpoint["after_id"] == changes[0].id
    ChangeJob.update(next_attempt_at=utc_now() + timedelta(hours=1)).where(
        ChangeJob.id != discovery.id
    ).execute()
    second = queue.claim_job("sweep-after-restart")
    plan = worker.compute_discovery_batch(second)
    assert plan["change_ids"] == [changes[1].id]
    queue.fail_claim(second, transient=True)
    assert ChangeJob.get_by_id(discovery.id).cursor == checkpoint
    ChangeJob.update(next_attempt_at=utc_now()).where(
        ChangeJob.id == discovery.id
    ).execute()
    second = queue.claim_job("sweep-retry")
    worker.publish_discovery_batch(second, worker.compute_discovery_batch(second))
    ChangeJob.update(next_attempt_at=utc_now() + timedelta(hours=1)).where(
        ChangeJob.id != discovery.id
    ).execute()
    third = queue.claim_job("sweep-last")
    worker.publish_discovery_batch(third, worker.compute_discovery_batch(third))
    assert ChangeJob.get_by_id(discovery.id).state == "done"
    assert {
        job.entity_id
        for job in ChangeJob.select().where(ChangeJob.job_type == "resolve_references")
    } == {change.id for change in changes}


def test_discovery_lost_lease_rolls_back_requested_jobs(intake):
    pending_change(intake)
    ChangeJob.delete().execute()
    with incident_core_repo.write_transaction():
        job = queue.request_job("discover_auth", intake[0][0].id)
    claim = queue.claim_job("expired-discovery")
    plan = worker.compute_discovery_batch(claim)
    ChangeJob.update(lease_expires_at=utc_now() - timedelta(seconds=1)).where(
        ChangeJob.id == job.id
    ).execute()
    with pytest.raises(queue.LostChangeLease):
        worker.publish_discovery_batch(claim, plan)
    assert (
        not ChangeJob.select()
        .where(ChangeJob.job_type == "resolve_references")
        .exists()
    )


def test_periodic_pending_sweep_restores_missing_jobs_but_keeps_dead_jobs(intake):
    first = pending_change(intake, change_id="first")
    second = pending_change(intake, change_id="second")
    ChangeJob.delete().execute()
    with incident_core_repo.write_transaction():
        dead = queue.request_job("resolve_references", second.id)
    ChangeJob.update(state="dead", last_error_class="internal_error").where(
        ChangeJob.id == dead.id
    ).execute()
    worker.schedule_pending_reconciliation()
    discovery = queue.claim_job("pending-recovery")
    assert discovery.job_type == "discover_graph"
    assert worker.process_claim(discovery) == "processed"
    assert (
        ChangeJob.get(
            ChangeJob.job_type == "resolve_references", ChangeJob.entity_id == first.id
        ).state
        == "pending"
    )
    assert ChangeJob.get_by_id(dead.id).state == "dead"


def test_catalog_creation_triggers_resolution_through_scheduler_worker(intake):
    change = pending_change(intake)
    process_resolution(change)
    ChangeJob.update(next_attempt_at=utc_now()).where(
        ChangeJob.job_type != "resolve_references"
    ).execute()
    service = services_repo.create_service(
        {"team": intake[0][2].team_id, "slug": "late-service", "name": "Late service"}
    )
    for _ in range(3):
        worker.process_change_jobs()
    assert ChangeService.get().service_id == service.id
    assert Change.get_by_id(change.id).mapping_status == "mapped"


def test_retry_audit_failure_rolls_back_generation_and_reference_reset(
    intake, monkeypatch
):
    change = pending_change(intake)
    ChangeServiceReference.update(expires_at=utc_now() - timedelta(seconds=1)).execute()
    job = process_resolution(change)
    before = ChangeServiceReference.get().expires_at

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(job_administration, "record_audit", fail)
    with pytest.raises(RuntimeError):
        job_administration.retry_job(
            job.id,
            job.requested_generation,
            actor_id=intake[0][3].id,
            integration_id=intake[0][0].id,
        )
    assert ChangeJob.get_by_id(job.id).requested_generation == job.requested_generation
    assert ChangeServiceReference.get().expires_at == before
    assert ChangeServiceReference.get().last_error_code == "pending_ttl_expired"


def test_disabled_worker_does_not_claim_jobs(intake):
    pending_change(intake)
    SystemSettings.update(change_worker_enabled=False).execute()
    assert worker.process_change_jobs() == 0
    assert not ChangeJob.select().where(ChangeJob.state == "running").exists()


def test_pending_sweep_deduplicates_change_across_pages(intake):
    SystemSettings.update(change_worker_batch_size=1).execute()
    change = pending_change(intake, slugs=["one", "two", "three"])
    ChangeJob.delete().where(ChangeJob.job_type != "resolve_references").execute()
    worker.schedule_pending_reconciliation()
    discovery = ChangeJob.get(ChangeJob.job_type == "discover_graph")
    resolution = ChangeJob.get(ChangeJob.job_type == "resolve_references")
    for _ in range(3):
        ChangeJob.update(next_attempt_at=utc_now() + timedelta(hours=1)).where(
            ChangeJob.id != discovery.id
        ).execute()
        claim = queue.claim_job("discovery")
        assert worker.process_claim(claim) == "processed"
    assert ChangeJob.get_by_id(discovery.id).state == "done"
    assert (
        ChangeJob.get_by_id(resolution.id).requested_generation
        == resolution.requested_generation
    )
    assert ChangeJob.get_by_id(resolution.id).entity_id == change.id


def test_dependency_mutations_advance_graph_and_request_discovery(intake):
    source = intake[0][2]
    target = create_service(source.team)
    before = ChangeGraphState.get_by_id(1).revision
    dependency = services_repo.create_service_dependency(
        source.id, {"depends_on_service": target.id}
    )
    services_repo.update_service_dependency(dependency.id, {"enabled": False})
    services_repo.soft_delete_service_dependency(dependency.id)
    assert ChangeGraphState.get_by_id(1).revision == before + 3
    job = ChangeJob.get(ChangeJob.job_type == "discover_graph")
    assert job.target_revision == before + 3


def test_scheduler_registers_worker_and_closes_its_connection(intake, monkeypatch):
    from app.services import scheduler
    from tests.test_retention_scheduler import _FakeDb

    fake = _FakeDb()
    monkeypatch.setattr(scheduler, "db", fake)
    monkeypatch.setattr(worker, "process_change_jobs", lambda: 3)
    assert scheduler.change_intelligence_job() == 3
    assert fake.closed and fake.connect_calls == fake.close_calls == 1
    jobs = []

    class FakeScheduler:
        running = False

        def add_job(self, function, *args, **kwargs):
            jobs.append((function, kwargs))

        def start(self):
            self.running = True

    monkeypatch.setattr(scheduler, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(scheduler, "_scheduler", None)
    scheduler.start_scheduler()
    registered = [
        options
        for function, options in jobs
        if function is scheduler.refresh_change_worker_schedule
    ]
    assert registered[0]["max_instances"] == 1
    assert registered[0]["seconds"] == 5
    assert registered[0]["args"] == (scheduler._scheduler,)


def test_running_scheduler_tracks_interval_even_when_queue_is_paused(client, admin_headers):
    from threading import Event

    from apscheduler.events import EVENT_JOB_EXECUTED
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.services.scheduler import refresh_change_worker_schedule

    def update(**values):
        response = client.patch("/api/admin/system-settings", json=values, headers=admin_headers)
        assert response.status_code == 200

    update(change_worker_interval_seconds=3600, change_worker_enabled=False)
    scheduler = BackgroundScheduler()
    registered, ran_at_short_interval, lengthened = Event(), Event(), Event()

    def observe(event):
        job = scheduler.get_job("change_intelligence_job")
        if job is None:
            return
        seconds = job.trigger.interval.total_seconds()
        if seconds == 3600:
            registered.set()
        if seconds == 1 and event.job_id == job.id and event.retval == 0:
            ran_at_short_interval.set()
        if seconds == 7200:
            lengthened.set()

    scheduler.add_listener(observe, EVENT_JOB_EXECUTED)
    scheduler.add_job(refresh_change_worker_schedule, "interval", seconds=0.2, args=(scheduler,))
    scheduler.start()
    try:
        assert registered.wait(10)
        update(change_worker_interval_seconds=1)
        # Several unchanged refreshes happen before this tick. They must not postpone it.
        assert ran_at_short_interval.wait(10)
        update(change_worker_interval_seconds=7200)
        assert lengthened.wait(10)
    finally:
        scheduler.shutdown()


def test_new_timing_applies_to_next_claim_and_reference_only(intake):
    SystemSettings.update(change_worker_lease_seconds=25, change_pending_ttl_seconds=120).execute()
    first = pending_change(intake)
    first_reference = ChangeServiceReference.get(ChangeServiceReference.change == first)
    claim = claim_resolution(first)
    assert claim.lease_expires_at - claim.updated_at == timedelta(seconds=25)
    assert abs((first_reference.expires_at - first_reference.created_at).total_seconds() - 120) < 2
    SystemSettings.update(change_worker_lease_seconds=40, change_pending_ttl_seconds=600).execute()
    assert ChangeJob.get_by_id(claim.id).lease_expires_at == claim.lease_expires_at
    assert ChangeServiceReference.get_by_id(first_reference.id).expires_at == first_reference.expires_at
    queue.renew_lease(claim)
    renewed = ChangeJob.get_by_id(claim.id)
    assert abs((renewed.lease_expires_at - renewed.updated_at).total_seconds() - 40) < 2
    second = pending_change(intake, change_id="second")
    newer = ChangeServiceReference.get(ChangeServiceReference.change == second)
    assert abs((newer.expires_at - newer.created_at).total_seconds() - 600) < 2
