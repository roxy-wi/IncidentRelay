"""Persistence primitives for Change Intelligence's first implementation stage."""

from peewee import Case

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db.models import ChangeJob


def request_job(
    job_type: str, entity_id: int, *, target_revision: int = 0
) -> ChangeJob:
    """Coalesce work inside the caller's transaction without changing a live lease.

    This only records durable intent. Claiming, retries and processing belong
    to the worker stage. The caller must commit its domain mutation and this
    request together; silently starting an independent transaction is unsafe.
    """
    if not database_proxy.in_transaction():
        raise RuntimeError("request_job requires the caller's transaction")
    now = utc_now()
    running = ChangeJob.state == "running"
    (
        ChangeJob.insert(
            job_type=job_type,
            entity_id=entity_id,
            target_revision=target_revision,
            next_attempt_at=now,
        )
        .on_conflict(
            conflict_target=[ChangeJob.job_type, ChangeJob.entity_id],
            update={
                ChangeJob.requested_generation: ChangeJob.requested_generation + 1,
                ChangeJob.target_revision: Case(
                    None,
                    ((ChangeJob.target_revision < target_revision, target_revision),),
                    ChangeJob.target_revision,
                ),
                ChangeJob.state: Case(None, ((running, ChangeJob.state),), "pending"),
                ChangeJob.attempts: Case(None, ((running, ChangeJob.attempts),), 0),
                ChangeJob.next_attempt_at: Case(
                    None, ((running, ChangeJob.next_attempt_at),), now
                ),
                ChangeJob.last_error_class: Case(
                    None, ((running, ChangeJob.last_error_class),), None
                ),
                ChangeJob.lease_owner: Case(
                    None, ((running, ChangeJob.lease_owner),), None
                ),
                ChangeJob.lease_token: Case(
                    None, ((running, ChangeJob.lease_token),), None
                ),
                ChangeJob.lease_expires_at: Case(
                    None, ((running, ChangeJob.lease_expires_at),), None
                ),
                ChangeJob.cursor: None,
                ChangeJob.updated_at: now,
            },
        )
        .execute()
    )
    return ChangeJob.get(
        ChangeJob.job_type == job_type, ChangeJob.entity_id == entity_id
    )
