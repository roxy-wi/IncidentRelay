"""Audited operator recovery of dead jobs and blocked reference attempts."""

from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo
from app.modules.db.models import (
    Change,
    ChangeIntegration,
    ChangeJob,
    ChangeServiceReference,
)
from app.services.audit import record_audit
from app.services.change_intelligence.administration import ChangeConflict, lock_catalog
from app.services.change_intelligence.authorization import lock_row
from app.services.change_intelligence.management import require_manager
from app.services.system_settings import get_settings


def integration_jobs(integration_id):
    """Constrain administration in SQL before pagination and serialization."""
    changes = Change.select(Change.id).where(Change.integration == integration_id)
    return ChangeJob.select().where(
        (
            (ChangeJob.job_type == "resolve_references")
            & ChangeJob.entity_id.in_(changes)
        )
        | (
            (ChangeJob.job_type == "discover_auth")
            & (ChangeJob.entity_id == integration_id)
        )
    )


def retry_job(job_id, expected_generation, *, actor_id, integration_id=None):
    """Restart one generation; original submitted identities and events stay fixed."""
    with incident_core_repo.write_transaction():
        lock_catalog()
        job = (
            (
                integration_jobs(integration_id)
                if integration_id is not None
                else ChangeJob.select()
            )
            .where(ChangeJob.id == job_id)
            .first()
        )
        if job is None:
            raise ChangeJob.DoesNotExist()
        change = (
            Change.get_or_none(Change.id == job.entity_id)
            if job.job_type == "resolve_references"
            else None
        )
        principal_id = (
            change.integration_id
            if change
            else (job.entity_id if job.job_type == "discover_auth" else None)
        )
        principal = (
            lock_row(
                ChangeIntegration.select().where(ChangeIntegration.id == principal_id)
            )
            if principal_id
            else None
        )
        require_manager(
            actor_id,
            principal.owner_group_id
            if integration_id is not None and principal
            else None,
        )
        if change:
            change = lock_row(Change.select().where(Change.id == change.id))
        current = lock_row(ChangeJob.select().where(ChangeJob.id == job.id))
        if current.requested_generation != expected_generation:
            raise ChangeConflict("Job changed; reload before retrying")
        repaired = 0
        if change:
            blocked = ChangeServiceReference.change == change.id
            blocked &= ChangeServiceReference.resolution_status.in_(
                ["denied", "invalid", "expired"]
            )
            # Resolved IDs remain pinned; a worker may restore their authority,
            # but never performs a new slug lookup for them.
            repaired = (
                ChangeServiceReference.update(last_error_code="retry_requested")
                .where(blocked)
                .execute()
            )
            ChangeServiceReference.update(
                expires_at=utc_now()
                + timedelta(seconds=get_settings().change_pending_ttl_seconds),
            ).where(
                blocked, ChangeServiceReference.resolved_service.is_null(True)
            ).execute()
            if repaired:
                change.revision += 1
                Change.update(revision=change.revision, updated_at=utc_now()).where(
                    Change.id == change.id
                ).execute()
        updated = changes_repo.request_job(
            job.job_type,
            job.entity_id,
            target_revision=change.revision if change else current.target_revision,
        )
        record_audit(
            "change_integration.job_retried",
            object_type="change_job",
            object_id=job.id,
            group_id=principal.owner_group_id if principal else None,
            user_id=actor_id,
            data={
                "integration_id": principal_id,
                "previous_generation": current.requested_generation,
                "requested_generation": updated.requested_generation,
                "references_requeued": repaired,
            },
        )
        return updated
