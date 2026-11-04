"""Process durable reference, discovery and correlation jobs in bounded batches."""

import logging
import os
import socket
import time
import uuid

from peewee import OperationalError, fn

from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo
from app.modules.db.models import (
    Change,
    ChangeGraphState,
    ChangeImpact,
    ChangeAlertGroupCorrelation,
    ChangeIntegration,
    ChangeJob,
    ChangeServiceReference,
)
from app.services.change_intelligence.authorization import lock_row
from app.services.change_intelligence.resolver import (
    StaleChangeInputs,
    compute_reference_batch,
    publish_reference_batch,
)
from app.services.change_intelligence.correlation import (
    automatic_work_needed,
    compute_correlation_batch,
    input_stamp,
    history_changes,
    mapping_current,
    publish_correlation_batch,
)
from app.services.change_intelligence.eligibility import eligible_episode_query
from app.services.change_intelligence.episode_discovery import (
    compute_episode_discovery,
    publish_episode_discovery,
)
from app.services.metrics import record_change_worker_result
from app.settings import Config

logger = logging.getLogger("oncall.change_intelligence")
DISABLED_JOB_TYPES = {
    "sync_service_timeline",
}


def schedule_pending_reconciliation():
    """Resume existing sweeps; periodically recover pending refs with no live job."""
    with incident_core_repo.write_transaction():
        lock_row(ChangeGraphState.select().where(ChangeGraphState.id == 1))
        job = ChangeJob.get_or_none(
            ChangeJob.job_type == "discover_graph", ChangeJob.entity_id == 1
        )
        if job and (
            job.state != "done"
            or (utc_now() - job.updated_at).total_seconds()
            < Config.CHANGE_PENDING_POLL_SECONDS
        ):
            return
        correlations = eligible_episode_query().exists() or (
            ChangeAlertGroupCorrelation.select()
            .where(ChangeAlertGroupCorrelation.active == True)
            .exists()
        )
        if correlations or (
            ChangeServiceReference.select()
            .where(ChangeServiceReference.resolution_status == "pending_resolution")
            .exists()
        ):
            pending_job = changes_repo.request_job("discover_graph", 1)
            ChangeJob.update(
                cursor={
                    "pending_only": not correlations,
                    "reconcile": correlations,
                }
            ).where(ChangeJob.id == pending_job.id).execute()


def compute_discovery_batch(claim):
    """Cursor over an integration's Changes or indexed pending reference rows."""
    graph_revision = ChangeGraphState.get_by_id(1).revision
    integration = (
        ChangeIntegration.get_or_none(ChangeIntegration.id == claim.entity_id)
        if claim.job_type == "discover_auth"
        else None
    )
    auth_revision = integration.auth_revision if integration else 0
    cursor = claim.cursor or {}
    pending_only = claim.job_type == "discover_graph" and cursor.get(
        "pending_only", False
    )
    reconcile = cursor.get("reconcile", False)
    stamp = {"graph_revision": graph_revision, "auth_revision": auth_revision}
    if any(cursor.get(key) != value for key, value in stamp.items()):
        cursor = {}
    if not pending_only:
        query = Change.select(Change.id, Change.id.alias("change_id")).where(
            Change.integration == claim.entity_id
            if claim.job_type == "discover_auth"
            else True
        )
        if reconcile:
            query = query.where(
                Change.id.in_(history_changes(utc_now()).select(Change.id))
                | Change.id.in_(
                    ChangeServiceReference.select(ChangeServiceReference.change).where(
                        ChangeServiceReference.resolution_status == "pending_resolution"
                    )
                )
                | Change.id.in_(
                    ChangeImpact.select(ChangeImpact.change).where(
                        ChangeImpact.active == True
                    )
                )
                | Change.id.in_(
                    ChangeAlertGroupCorrelation.select(
                        ChangeAlertGroupCorrelation.change
                    ).where(ChangeAlertGroupCorrelation.active == True)
                )
            )
        column = Change.id
    else:
        query = ChangeServiceReference.select(
            ChangeServiceReference.id, ChangeServiceReference.change.alias("change_id")
        ).where(ChangeServiceReference.resolution_status == "pending_resolution")
        column = ChangeServiceReference.id
    upper = cursor.get("upper_id")
    if upper is None:
        upper = query.select(fn.MAX(column)).scalar() or 0
    rows = list(
        query.where(column > cursor.get("after_id", 0), column <= upper)
        .order_by(column)
        .limit(Config.CHANGE_WORKER_BATCH_SIZE)
        .dicts()
    )
    after = rows[-1]["id"] if rows else upper
    return {
        "stamp": stamp,
        "integration": integration,
        "change_ids": sorted({row["change_id"] for row in rows}),
        "upper_id": upper,
        "after_id": after,
        "complete": after >= upper or len(rows) < Config.CHANGE_WORKER_BATCH_SIZE,
        "pending_only": pending_only,
        "reconcile": reconcile,
    }


def publish_discovery_batch(claim, plan):
    """Requests and sweep progress commit together; queue locks are always last."""
    with incident_core_repo.write_transaction():
        graph = lock_row(ChangeGraphState.select().where(ChangeGraphState.id == 1))
        integration = None
        if plan["integration"]:
            integration = lock_row(
                ChangeIntegration.select().where(
                    ChangeIntegration.id == plan["integration"].id
                )
            )
        if graph.revision != plan["stamp"]["graph_revision"] or (
            integration and integration.auth_revision != plan["stamp"]["auth_revision"]
        ):
            raise StaleChangeInputs()
        # Never hold our own job lock while requesting other jobs. A final fence
        # failure rolls back those requests as well as the cursor checkpoint.
        changes = [
            lock_row(Change.select().where(Change.id == change_id))
            for change_id in plan["change_ids"]
        ]
        for change in filter(None, changes):
            if (
                plan["reconcile"]
                and automatic_work_needed(change)
                and mapping_current(
                    change,
                    change.integration,
                    input_stamp(change, change.integration, graph.revision),
                )
            ):
                existing = ChangeJob.get_or_none(
                    ChangeJob.job_type == "refresh_correlations",
                    ChangeJob.entity_id == change.id,
                )
                if existing is None or existing.state == "done":
                    changes_repo.request_job(
                        "refresh_correlations",
                        change.id,
                        target_revision=change.revision,
                    )
                continue
            existing = lock_row(
                ChangeJob.select().where(
                    ChangeJob.job_type == "resolve_references",
                    ChangeJob.entity_id == change.id,
                )
            )
            if existing and existing.state == "dead":
                continue
            if (
                existing
                and existing.state in {"pending", "running"}
                and existing.target_revision >= change.revision
            ):
                if existing.requested_generation > existing.claimed_generation or (
                    existing.graph_revision == graph.revision
                    and existing.auth_revision == change.integration.auth_revision
                ):
                    continue
            changes_repo.request_job(
                "resolve_references", change.id, target_revision=change.revision
            )
        changes_repo.lock_claim(claim)
        cursor = (
            None
            if plan["complete"]
            else {
                **plan["stamp"],
                "upper_id": plan["upper_id"],
                "after_id": plan["after_id"],
                "pending_only": plan["pending_only"],
                "reconcile": plan["reconcile"],
            }
        )
        changes_repo.finish_claim(
            claim,
            cursor=cursor,
            delay=None if plan["complete"] else 0,
            stamp={**plan["stamp"], "engine_version": "discovery-v1"},
        )


def process_claim(claim):
    """Calculation is outside write locks; all publication paths are fenced."""
    try:
        if claim.job_type == "resolve_references":
            plan = compute_reference_batch(claim)
            publish_reference_batch(claim, plan)
        elif claim.job_type in {"discover_auth", "discover_graph"}:
            plan = compute_discovery_batch(claim)
            publish_discovery_batch(claim, plan)
        elif claim.job_type == "discover_episode":
            plan = compute_episode_discovery(claim)
            publish_episode_discovery(claim, plan)
        elif claim.job_type in {"refresh_impacts", "refresh_correlations"}:
            plan = compute_correlation_batch(claim)
            publish_correlation_batch(claim, plan)
        elif claim.job_type in DISABLED_JOB_TYPES:
            with incident_core_repo.write_transaction():
                changes_repo.lock_claim(claim)
                changes_repo.finish_claim(claim, error_class="not_enabled")
        else:
            raise ValueError("Unsupported Change job type")
        record_change_worker_result("processed")
        return "processed"
    except (StaleChangeInputs, changes_repo.LostChangeLease):
        changes_repo.retry_contention(lambda: changes_repo.release_stale_claim(claim))
        record_change_worker_result("stale")
        return "stale"
    except Exception as error:
        transient = isinstance(
            error, OperationalError
        ) and changes_repo.transient_database_error(error)
        changes_repo.retry_contention(
            lambda: changes_repo.fail_claim(claim, transient=transient)
        )
        # Exception messages may contain submitted values or SQL parameters.
        logger.error("Change worker failed: %s", type(error).__name__)
        record_change_worker_result("failed")
        return "failed"


def process_change_jobs():
    """One bounded scheduler tick; independent processes may safely compete."""
    if not Config.CHANGE_WORKER_ENABLED:
        return 0
    changes_repo.retry_contention(schedule_pending_reconciliation)
    owner = f"{socket.gethostname()[:100]}:{os.getpid()}:{uuid.uuid4().hex}"
    processed = 0
    deadline = time.monotonic() + 10
    for _ in range(Config.CHANGE_WORKER_JOBS_PER_TICK):
        if time.monotonic() >= deadline:
            break
        claim = changes_repo.claim_job(owner)
        if claim is None:
            break
        record_change_worker_result("reclaimed" if claim.reclaimed else "claimed")
        process_claim(claim)
        processed += 1
    return processed
