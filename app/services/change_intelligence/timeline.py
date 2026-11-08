"""Bounded, fenced publication of safe Change projections to Service timelines."""

from peewee import fn

from app.modules.db import changes_repo, incident_core_repo
from app.modules.db.models import (
    Change,
    ChangeEvent,
    ChangeGraphState,
    ChangeImpact,
    ChangeIntegration,
    ChangeJob,
    ChangeService,
    Service,
    ServiceEvent,
)
from app.services.change_intelligence.authorization import lock_row
from app.services.change_intelligence.reading import current_impacts, current_links
from app.services.change_intelligence.resolver import StaleChangeInputs
from app.services.system_settings import get_settings

ENGINE_VERSION = "timeline-v1"


def request_publication(change):
    """Do not reset retry limits when an unchanged projection is polled again."""
    existing = ChangeJob.get_or_none(
        ChangeJob.job_type == "sync_service_timeline", ChangeJob.entity_id == change.id
    )
    if (
        existing
        and existing.target_revision >= change.revision
        and (
            existing.state == "dead"
            or (existing.state == "pending" and existing.attempts > 0)
        )
    ):
        return
    changes_repo.request_job(
        "sync_service_timeline", change.id, target_revision=change.revision
    )


def input_stamp(change, integration, graph_revision):
    """Capture revisions that must still match when the batch is published."""
    return {
        "target_revision": change.revision,
        "auth_revision": integration.auth_revision,
        "graph_revision": graph_revision,
        "engine_version": ENGINE_VERSION,
    }


def missing_events(change, *, inferred=False):
    """Use indexed provenance to skip published rows, including after a restart."""
    model = ChangeImpact if inferred else ChangeService
    links = current_impacts(None) if inferred else current_links(None)
    relation = "inferred_impact" if inferred else ChangeService.relation_type
    existing = ServiceEvent.select(ServiceEvent.id).where(
        ServiceEvent.change_event == ChangeEvent.id,
        ServiceEvent.service == model.service,
        ServiceEvent.change_relation_type == relation,
    )
    return (
        links.join_from(model, ChangeEvent, on=(ChangeEvent.change == model.change))
        .where(model.change == change.id, ~fn.EXISTS(existing))
        .select(
            ChangeEvent.id.alias("event_id"),
            model.service.alias("service_id"),
            ChangeEvent.occurred_at,
            Service.group.alias("group_id"),
            Service.team.alias("team_id"),
            *([] if inferred else [ChangeService.relation_type]),
        )
        .distinct()
        .order_by(ChangeEvent.id, model.service)
    )


def compute_timeline_batch(claim):
    """Select at most one batch; never copy provider text or raw event payloads."""
    change = Change.get_or_none(Change.id == claim.entity_id)
    if change is None:
        return None
    stamp = input_stamp(
        change, change.integration, ChangeGraphState.get_by_id(1).revision
    )
    limit = get_settings().change_worker_batch_size
    rows = list(missing_events(change).limit(limit).dicts())
    if len(rows) < limit:
        for row in (
            missing_events(change, inferred=True).limit(limit - len(rows)).dicts()
        ):
            rows.append({**row, "relation_type": "inferred_impact"})
    return {
        "change": change,
        "stamp": stamp,
        "rows": rows,
        "complete": len(rows) < limit,
    }


def publish_timeline_batch(claim, plan):
    """Commit provenance and queue progress together, under the usual lock order."""
    with incident_core_repo.write_transaction():
        if plan is None:
            changes_repo.lock_claim(claim)
            changes_repo.finish_claim(claim, error_class="entity_missing")
            return
        graph = lock_row(ChangeGraphState.select().where(ChangeGraphState.id == 1))
        integration = lock_row(
            ChangeIntegration.select().where(
                ChangeIntegration.id == plan["change"].integration_id
            )
        )
        change = lock_row(Change.select().where(Change.id == claim.entity_id))
        if change is None or plan["stamp"] != input_stamp(
            change, integration, graph.revision
        ):
            raise StaleChangeInputs()
        changes_repo.lock_claim(claim)
        # A resolver/correlation pass may have been requested without advancing
        # the graph. Check its SQL freshness gate again while publication is locked.
        service_ids = [row["service_id"] for row in plan["rows"]]
        direct = set(
            current_links(None)
            .where(
                ChangeService.change == change.id,
                ChangeService.service.in_(service_ids),
            )
            .select(ChangeService.service, ChangeService.relation_type)
            .tuples()
        )
        inferred = set(
            current_impacts(None)
            .where(
                ChangeImpact.change == change.id, ChangeImpact.service.in_(service_ids)
            )
            .select(ChangeImpact.service)
            .distinct()
            .tuples()
        )
        for row in plan["rows"]:
            service_id, relation = row["service_id"], row["relation_type"]
            if (service_id, relation) not in direct and not (
                relation == "inferred_impact" and (service_id,) in inferred
            ):
                raise StaleChangeInputs()
            ServiceEvent.get_or_create(
                service=service_id,
                change_event=row["event_id"],
                change_relation_type=relation,
                defaults={
                    "group": row["group_id"],
                    "team": row["team_id"],
                    "category": "change",
                    "event_type": "change.recorded",
                    "title": "Related change",
                    "source": "change_intelligence",
                    "dedup_key": f"{row['event_id']}:{relation}",
                    "occurred_at": row["occurred_at"],
                    "payload": {
                        "change_uid": str(change.uid),
                        "kind": change.kind,
                        "relation_type": relation,
                    },
                },
            )
        changes_repo.finish_claim(
            claim,
            stamp=plan["stamp"],
            delay=None if plan["complete"] else 0,
        )
