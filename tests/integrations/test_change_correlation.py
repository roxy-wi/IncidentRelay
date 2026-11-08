"""Automatic proposals obey policy, chronology, authority and publication fences."""

from datetime import timedelta

import pytest

from app.api.schemas.change_events import ChangeEventInput
from app.modules.common import utc_now
from app.modules.db import (
    alert_episodes_repo,
    alerts_repo,
    changes_repo,
    incident_core_repo,
    services_repo,
)
from app.modules.db.models import (
    SystemSettings,
    Alert,
    AlertGroup,
    AlertGroupEpisode,
    Change,
    ChangeAlertGroupCorrelation,
    ChangeImpact,
    ChangeIntegration,
    ChangeJob,
    Service,
    ServiceDependency,
)
from app.services.change_intelligence import (
    correlation as engine,
    episode_discovery,
    ingestion,
    worker,
)
from app.services.change_intelligence.eligibility import (
    episode_eligibility,
    exclusion_matches,
)
from app.services.change_intelligence.resolver import StaleChangeInputs
from tests.factories import create_service, unique
from tests.integrations.test_change_events import event_payload, intake, setup_identity
from tests.integrations.test_change_worker import process_resolution

__all__ = ["intake", "setup_identity"]


def opt_in(service, exclusions=None):
    Service.update(
        change_correlation_enabled=True, change_correlation_exclusions=exclusions or []
    ).where(Service.id == service.id).execute()
    return Service.get_by_id(service.id)


def episode_for(service, *, start=None, labels=None, source="prometheus"):
    start = start or utc_now()
    group = alerts_repo.create_alert_group(
        team=service.team_id,
        service=service.id,
        source=source,
        group_key=unique("cycle"),
        title="Example",
        first_seen_at=start,
    )
    Alert.create(
        group=group,
        team=service.team_id,
        service=service.id,
        source=source,
        group_key=group.group_key,
        dedup_key=unique("alert"),
        title="Example",
        labels=labels or {},
        first_seen_at=start,
    )
    alerts_repo.recalculate_alert_group(group)
    return AlertGroupEpisode.get_by_id(group.current_episode_id)


def operation(intake, *, at=None, event_type="change.succeeded", **fields):
    identity, _, _, token = intake
    at = at or utc_now() - timedelta(minutes=30)
    payload = event_payload(
        identity,
        occurred_at=at.isoformat() + "Z",
        event_type=event_type,
        **fields,
    )
    if "changed_services" in fields:
        payload.pop("changed_service_ids", None)
    ingestion.ingest_event(ChangeEventInput.model_validate(payload), token)
    change = Change.get(Change.external_change_id == fields.get("change_id", "build-1"))
    process_resolution(change)
    return Change.get_by_id(change.id)


def claim_kind(kind, entity_id):
    now = utc_now()
    target = ChangeJob.get(ChangeJob.job_type == kind, ChangeJob.entity_id == entity_id)
    ChangeJob.update(next_attempt_at=now + timedelta(hours=1)).execute()
    ChangeJob.update(next_attempt_at=now - timedelta(seconds=1)).where(
        ChangeJob.id == target.id
    ).execute()
    return changes_repo.claim_job("correlation-test")


def run_change(change, kind="refresh_impacts"):
    claim = claim_kind(kind, change.id)
    assert claim is not None
    assert worker.process_claim(claim) == "processed"
    return ChangeJob.get_by_id(claim.id)


def request_change(change):
    with incident_core_repo.write_transaction():
        changes_repo.request_job(
            "refresh_correlations", change.id, target_revision=change.revision
        )


def edge(provider, consumer, **kwargs):
    return ServiceDependency.create(
        service=consumer, depends_on_service=provider, **kwargs
    )


def test_disabled_and_unmapped_groups_do_not_enqueue_search(intake):
    service = intake[0][2]
    episode = episode_for(service)
    assert episode_eligibility(episode) == "disabled"
    assert (
        not ChangeJob.select().where(ChangeJob.job_type == "discover_episode").exists()
    )
    with incident_core_repo.write_transaction():
        group = AlertGroup.get_by_id(episode.alert_group_id)
        group.service = None
        group.save()
        alert_episodes_repo.refresh_context(group)
    assert episode_eligibility(AlertGroupEpisode.get_by_id(episode.id)) == "no_service"
    assert (
        not ChangeJob.select().where(ChangeJob.job_type == "discover_episode").exists()
    )


@pytest.mark.parametrize(
    ("child", "rule", "matches"),
    [
        (
            {"source": "heartbeat", "labels": {"kind": "synthetic"}},
            {"source": "heartbeat", "labels": {"kind": "synthetic"}},
            True,
        ),
        (
            {"source": "prometheus", "labels": {"kind": "synthetic"}},
            {"source": "heartbeat", "labels": {"kind": "synthetic"}},
            False,
        ),
        ({"source": "heartbeat", "labels": {}}, {"labels": {"kind": ""}}, False),
        (
            {"labels": {"kind": "synthetic-extra"}},
            {"labels": {"kind": "synthetic"}},
            False,
        ),
        ({"source": "heartbeat"}, {}, False),
    ],
)
def test_exclusion_is_exact_and_all_clauses_match_one_child(child, rule, matches):
    assert exclusion_matches(child, rule) is matches


def test_mixed_children_and_closed_snapshot(intake):
    service = opt_in(intake[0][2], [{"source": "heartbeat"}])
    episode = episode_for(service, source="heartbeat")
    assert episode_eligibility(episode) == "all_excluded"
    group = episode.alert_group
    Alert.create(
        group=group,
        team=service.team_id,
        source="prometheus",
        dedup_key=unique("ok"),
        group_key=group.group_key,
        title="Real failure",
        labels={"kind": "real"},
    )
    alerts_repo.recalculate_alert_group(group)
    episode = AlertGroupEpisode.get_by_id(episode.id)
    assert episode_eligibility(episode) == "eligible"
    assert (
        ChangeJob.get(ChangeJob.job_type == "discover_episode").target_revision
        == episode.context_revision
    )
    alerts_repo.resolve_alert_group(group.id)
    closed = AlertGroupEpisode.get_by_id(episode.id)
    saved = closed.correlation_context
    Alert.update(labels={"kind": "changed"}, source="heartbeat").where(
        Alert.group == group.id
    ).execute()
    with incident_core_repo.write_transaction():
        current = AlertGroup.get_by_id(group.id)
        current.status = "firing"
        current.save()
        next_episode = alert_episodes_repo.open_episode(current, started_at=utc_now())
    assert next_episode.id != closed.id
    assert AlertGroupEpisode.get_by_id(closed.id).correlation_context == saved
    assert episode_eligibility(AlertGroupEpisode.get_by_id(closed.id)) == "eligible"
    assert not AlertGroupEpisode.get_by_id(next_episode.id).correlation_context[
        "children"
    ]


def test_existing_episode_without_context_stays_unknown(intake):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    AlertGroupEpisode.update(correlation_context=None).where(
        AlertGroupEpisode.id == episode.id
    ).execute()
    ChangeJob.delete().where(ChangeJob.job_type == "discover_episode").execute()
    alerts_repo.recalculate_alert_group(episode.alert_group)
    assert AlertGroupEpisode.get_by_id(episode.id).correlation_context is None
    assert (
        not ChangeJob.select().where(ChangeJob.job_type == "discover_episode").exists()
    )


def test_change_after_alert_produces_exact_episode_suggestion(intake):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    change = operation(intake)
    job = run_change(change)
    rows = engine.current_suggestions(episode)
    assert len(rows) == 1 and rows[0].reason == "changed"
    assert rows[0].relation_type == "potential_cause"
    assert rows[0].evidence["environment"] == "unknown"
    assert rows[0].input_stamp["episode_revision"] == episode.context_revision
    assert job.state == "done" and job.last_error_class is None
    assert ChangeImpact.select().where(ChangeImpact.active == True).count() == 1
    assert AlertGroup.get_by_id(episode.alert_group_id).status == "firing"
    request_change(change)
    run_change(change, "refresh_correlations")
    assert ChangeAlertGroupCorrelation.select().count() == 1


def test_alert_after_change_discovers_even_old_running_operation(intake):
    service = opt_in(intake[0][2])
    change = operation(
        intake, event_type="change.started", at=utc_now() - timedelta(days=20)
    )
    run_change(change)
    assert ChangeAlertGroupCorrelation.select().count() == 0
    episode = episode_for(service)
    claim = claim_kind("discover_episode", episode.id)
    assert worker.process_claim(claim) == "processed"
    run_change(change, "refresh_correlations")
    assert len(engine.current_suggestions(episode)) == 1


def test_reverse_graph_cycle_diamond_and_disabled_edges(intake):
    origin = opt_in(intake[0][2])
    left, right, target = [create_service(origin.team) for _ in range(3)]
    opt_in(target)
    first = edge(origin, left)
    edge(origin, right)
    edge(left, target)
    edge(right, target)
    edge(target, origin)
    blocked = create_service(origin.team)
    edge(origin, blocked, correlation_enabled=False)
    informational = create_service(origin.team)
    edge(origin, informational, dependency_type="informational")
    staging = create_service(origin.team, environment="staging")
    edge(origin, staging)
    episode = episode_for(target)
    change = operation(intake, environment="production")
    run_change(change)
    row = engine.current_suggestions(episode)[0]
    assert row.reason == "dependency" and row.evidence["depth"] == 2
    assert row.evidence["path"][0]["dependency_id"] == first.id
    assert ChangeImpact.select().where(ChangeImpact.active == True).count() == 4
    assert ChangeAlertGroupCorrelation.select().count() == 1
    assert not left.change_correlation_enabled  # Intermediate opt-in is irrelevant.


@pytest.mark.parametrize(
    ("offset", "event_type", "expected"),
    [
        (-1, "change.succeeded", 0),
        (0, "change.succeeded", 1),
        (7200, "change.succeeded", 1),
        (7201, "change.succeeded", 0),
        (30, "change.updated", 0),
    ],
)
def test_interval_boundaries_use_episode_start(intake, offset, event_type, expected):
    service = opt_in(intake[0][2])
    start = utc_now() - timedelta(hours=3)
    episode = episode_for(service, start=start + timedelta(seconds=offset))
    change = operation(intake, at=start, event_type=event_type)
    run_change(change)
    assert len(engine.current_suggestions(episode)) == expected


def test_unknown_start_old_episode_and_environment_mismatch_skip(intake):
    service = opt_in(intake[0][2])
    episode = episode_for(service, start=utc_now() - timedelta(days=9))
    assert episode_eligibility(episode) == "outside_history"
    recent = episode_for(service)
    change = operation(intake, environment="staging")
    run_change(change)
    assert engine.current_suggestions(recent) == []
    AlertGroupEpisode.update(start_quality="unknown", started_at=None).where(
        AlertGroupEpisode.id == recent.id
    ).execute()
    assert (
        episode_eligibility(AlertGroupEpisode.get_by_id(recent.id)) == "unknown_start"
    )


@pytest.mark.parametrize(
    "mutation", ["graph", "authority", "change", "episode", "generation", "lease"]
)
def test_stale_computation_cannot_publish(intake, mutation):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    change = operation(intake)
    claim = claim_kind("refresh_impacts", change.id)
    plan = engine.compute_correlation_batch(claim)
    if mutation == "graph":
        services_repo.update_service(service.id, {"change_correlation_enabled": False})
    elif mutation == "authority":
        ChangeIntegration.update(
            auth_revision=ChangeIntegration.auth_revision + 1
        ).execute()
    elif mutation == "change":
        Change.update(revision=Change.revision + 1).where(
            Change.id == change.id
        ).execute()
    elif mutation == "episode":
        AlertGroupEpisode.update(
            context_revision=AlertGroupEpisode.context_revision + 1
        ).where(AlertGroupEpisode.id == episode.id).execute()
    elif mutation == "generation":
        with incident_core_repo.write_transaction():
            changes_repo.request_job("refresh_impacts", change.id)
    else:
        ChangeJob.update(lease_expires_at=utc_now() - timedelta(seconds=1)).where(
            ChangeJob.id == claim.id
        ).execute()
    with pytest.raises((StaleChangeInputs, changes_repo.LostChangeLease)):
        engine.publish_correlation_batch(claim, plan)
    assert ChangeAlertGroupCorrelation.select().count() == 0
    assert ChangeImpact.select().count() == 0


def test_failed_publication_rolls_back_and_can_retry(intake, monkeypatch):
    service = opt_in(intake[0][2])
    episode_for(service)
    change = operation(intake)
    claim = claim_kind("refresh_impacts", change.id)
    plan = engine.compute_correlation_batch(claim)
    original = changes_repo.finish_claim

    def fail(*args, **kwargs):
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(changes_repo, "finish_claim", fail)
    with pytest.raises(RuntimeError):
        engine.publish_correlation_batch(claim, plan)
    assert ChangeAlertGroupCorrelation.select().count() == 0
    assert ChangeImpact.select().count() == 0
    monkeypatch.setattr(changes_repo, "finish_claim", original)
    engine.publish_correlation_batch(claim, plan)
    assert ChangeAlertGroupCorrelation.select().count() == 1


def test_manual_decision_survives_recompute_and_disable_hides_immediately(intake):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    change = operation(intake)
    run_change(change)
    row = ChangeAlertGroupCorrelation.get()
    ChangeAlertGroupCorrelation.update(
        review_status="rejected",
        relation_type="context",
        row_version=3,
        review_evidence={"original": "snapshot"},
        reviewed_at=utc_now(),
    ).where(ChangeAlertGroupCorrelation.id == row.id).execute()
    request_change(change)
    run_change(change, "refresh_correlations")
    row = ChangeAlertGroupCorrelation.get()
    assert row.review_status == "rejected" and row.relation_type == "context"
    assert row.review_evidence == {"original": "snapshot"} and row.row_version == 3
    ChangeAlertGroupCorrelation.update(review_status="suggested").execute()
    assert len(engine.current_suggestions(episode)) == 1
    services_repo.update_service(service.id, {"change_correlation_enabled": False})
    assert engine.current_suggestions(episode) == []
    assert worker.process_claim(claim_kind("discover_graph", 1)) == "processed"
    process_resolution(change)
    run_change(Change.get_by_id(change.id))
    assert not ChangeAlertGroupCorrelation.get().active
    assert ChangeAlertGroupCorrelation.get().review_evidence == {"original": "snapshot"}


def test_bounded_batches_continue_without_duplicate_rows(intake):
    service = opt_in(intake[0][2])
    episodes = [episode_for(service) for _ in range(3)]
    change = operation(intake)
    SystemSettings.update(change_worker_batch_size=1).execute()
    for _ in episodes:
        run_change(change)
    job = ChangeJob.get(ChangeJob.job_type == "refresh_impacts")
    if job.state == "pending":
        run_change(change)
    assert ChangeAlertGroupCorrelation.select().count() == 3
    assert ChangeImpact.select().count() == 1
    assert all(len(engine.current_suggestions(episode)) == 1 for episode in episodes)


def test_limits_do_not_publish_an_arbitrary_partial_graph(intake, monkeypatch):
    service = opt_in(intake[0][2])
    episode_for(service)
    edge(service, create_service(service.team))
    change = operation(intake)
    monkeypatch.setattr(engine, "MAX_IMPACTS", 1)
    job = run_change(change)
    assert job.last_error_class == "limit_exceeded"
    assert ChangeImpact.select().count() == 0
    assert ChangeAlertGroupCorrelation.select().count() == 0


def test_ineligible_old_discovery_finishes_without_retry_loop(intake):
    service = intake[0][2]
    episode = episode_for(service)
    with incident_core_repo.write_transaction():
        changes_repo.request_job("discover_episode", episode.id)
    claim = claim_kind("discover_episode", episode.id)
    plan = episode_discovery.compute_episode_discovery(claim)
    assert plan["ids"] == [] and plan["reason"] == "disabled"
    episode_discovery.publish_episode_discovery(claim, plan)
    job = ChangeJob.get_by_id(claim.id)
    assert job.state == "done" and job.last_error_class == "disabled"


def test_unverified_assertion_does_not_seed_graph_but_explicit_grant_does(intake):
    from tests.integrations.test_change_integrations import grant

    target = opt_in(create_service(intake[0][2].team))
    episode = episode_for(target)
    change = operation(intake, changed_service_ids=[], affected_service_ids=[target.id])
    run_change(change)
    assert engine.current_suggestions(episode) == []
    assert ChangeImpact.select().count() == 0
    grant(intake[0], capability="reported_affected", service=target.id)
    trusted = operation(
        intake,
        change_id="trusted",
        event_id="trusted",
        changed_service_ids=[],
        affected_service_ids=[target.id],
    )
    run_change(trusted)
    rows = engine.current_suggestions(episode)
    assert len(rows) == 1 and rows[0].reason == "reported_affected"
    assert ChangeImpact.select().count() == 0  # Reported assertions never seed paths.


def test_graph_sweep_reenables_eligible_history_in_bounded_batches(intake):
    service = intake[0][2]
    episode = episode_for(service)
    changes = [
        operation(intake, change_id=f"operation-{index}", event_id=f"event-{index}")
        for index in range(3)
    ]
    for change in changes:
        run_change(change)
    assert not ChangeAlertGroupCorrelation.select().exists()
    services_repo.update_service(service.id, {"change_correlation_enabled": True})
    SystemSettings.update(change_worker_batch_size=1).execute()
    for _ in range(4):
        claim = claim_kind("discover_graph", 1)
        if claim is None:
            break
        assert worker.process_claim(claim) == "processed"
    for change in changes:
        process_resolution(change)
        refreshed = Change.get_by_id(change.id)
        run_change(refreshed)
    assert len(engine.current_suggestions(episode)) == 3
    assert ChangeAlertGroupCorrelation.select().count() == 3


def test_reconciliation_catches_episode_created_during_policy_enable(intake):
    service = intake[0][2]
    episode = episode_for(service)
    change = operation(intake)
    run_change(change)
    # Simulate the lifecycle reading disabled immediately before opt-in commits.
    # The periodic sweep must recover even if the original discovery was done.
    Service.update(change_correlation_enabled=True).where(
        Service.id == service.id
    ).execute()
    ChangeJob.delete().where(
        ChangeJob.job_type.in_(("discover_episode", "discover_graph"))
    ).execute()
    worker.schedule_pending_reconciliation()
    assert worker.process_claim(claim_kind("discover_graph", 1)) == "processed"
    run_change(change, "refresh_correlations")
    assert len(engine.current_suggestions(episode)) == 1


def test_invalid_interval_and_equal_terminal_conflict_publish_no_cause(intake):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    change = operation(intake)
    original_end = change.completed_at
    Change.update(started_at=original_end + timedelta(seconds=1)).where(
        Change.id == change.id
    ).execute()
    job = run_change(Change.get_by_id(change.id))
    assert job.last_error_class == "invalid_interval"
    assert engine.current_suggestions(episode) == []
    conflict = operation(
        intake,
        event_id="failure-at-same-time",
        at=original_end,
        event_type="change.failed",
    )
    assert conflict.lifecycle_conflict
    job = run_change(conflict)
    assert job.last_error_class == "unknown_interval"
    assert engine.current_suggestions(episode) == []


def test_context_revision_immediately_hides_changed_exclusions(intake):
    service = opt_in(intake[0][2], [{"labels": {"kind": "synthetic"}}])
    episode = episode_for(service, labels={"kind": "real"})
    change = operation(intake)
    run_change(change)
    assert len(engine.current_suggestions(episode)) == 1
    with incident_core_repo.write_transaction():
        group = incident_core_repo.lock_alert_group(episode.alert_group_id)
        child = Alert.get(Alert.group == group.id)
        child.labels = {"kind": "synthetic"}
        child.save()
        alert_episodes_repo.refresh_context(group, observed_alert=child)
    # Even a caller holding an older model instance cannot display the old result.
    assert engine.current_suggestions(episode) == []
    current = AlertGroupEpisode.get_by_id(episode.id)
    assert episode_eligibility(current) == "all_excluded"
    assert current.context_revision > episode.context_revision


def test_old_completed_change_does_not_create_automatic_search(intake):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    change = operation(intake, at=utc_now() - timedelta(days=20))
    assert (
        not ChangeJob.select()
        .where(
            ChangeJob.entity_id == change.id,
            ChangeJob.job_type.in_(("refresh_impacts", "refresh_correlations")),
        )
        .exists()
    )
    plan = episode_discovery.compute_episode_discovery(
        claim_kind("discover_episode", episode.id)
    )
    assert plan["ids"] == []


def test_episode_reconciliation_does_not_starve_old_pending_references(intake):
    from tests.integrations.test_change_worker import pending_change

    service = opt_in(intake[0][2])
    episode_for(service)
    change = pending_change(intake)
    ChangeJob.delete().where(ChangeJob.job_type == "resolve_references").execute()
    ChangeJob.delete().where(ChangeJob.job_type == "discover_graph").execute()
    worker.schedule_pending_reconciliation()
    claim = claim_kind("discover_graph", 1)
    assert worker.process_claim(claim) == "processed"
    assert (
        ChangeJob.get(
            ChangeJob.job_type == "resolve_references", ChangeJob.entity_id == change.id
        ).state
        == "pending"
    )


def test_pending_reference_poll_does_not_restart_dead_projection(intake, monkeypatch):
    opt_in(intake[0][2])
    change = operation(intake, changed_services=[{"service_slug": "not-created-yet"}])
    claim = claim_kind("refresh_impacts", change.id)

    def fail(*args, **kwargs):
        raise RuntimeError("injected calculation failure")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "compute_paths", fail)
        assert worker.process_claim(claim) == "failed"
    failed = ChangeJob.get_by_id(claim.id)
    assert failed.state == "dead"
    process_resolution(change)
    after = ChangeJob.get_by_id(claim.id)
    assert after.state == "dead"
    assert after.requested_generation == failed.requested_generation


@pytest.mark.parametrize("review", ["suggested", "confirmed", "rejected"])
def test_retention_removes_only_unreviewed_derived_history(intake, review):
    from app.services.alerts.retention import cleanup_alert_history

    service = opt_in(intake[0][2])
    episode = episode_for(service)
    change = operation(intake)
    run_change(change)
    ChangeAlertGroupCorrelation.update(
        review_status=review,
        review_evidence=None if review == "suggested" else {"kept": True},
    ).execute()
    alerts_repo.resolve_alert_group(episode.alert_group_id)
    result = cleanup_alert_history(
        retention_days=1, now=utc_now() + timedelta(days=2), batch_size=1
    )
    assert result["groups_deleted"] == int(review == "suggested")
    assert AlertGroupEpisode.select().count() == int(review != "suggested")
    assert ChangeAlertGroupCorrelation.select().count() == int(review != "suggested")
    assert Change.get_by_id(
        change.id
    )  # Operation history belongs to a separate retention policy.



def test_reused_sql_id_does_not_rebind_historical_episode_to_new_service(intake):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    service.delete_instance()
    replacement = Service.create(
        id=service.id, team=service.team_id, name="Replacement", slug="replacement",
        change_correlation_enabled=True,
    )
    assert replacement.uid != service.uid
    assert episode_eligibility(episode) == "service_replaced"
