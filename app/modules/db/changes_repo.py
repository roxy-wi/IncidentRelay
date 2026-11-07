"""Durable Change work with fenced leases and coalesced generations."""

from datetime import timedelta
import random
import time
import uuid

from peewee import Case, OperationalError, SqliteDatabase

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db.models import ChangeJob
from app.modules.db.incident_core_repo import write_transaction
from app.services.system_settings import get_settings


class LostChangeLease(RuntimeError):
    """A stale worker must roll back all publication writes."""


def transient_database_error(error):
    """Classify contention without inspecting or logging SQL parameter values."""
    original = (
        getattr(error, "orig", None) or error.__cause__ or error.__context__ or error
    )
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return code in {"40001", "40P01", "55P03", "57014"} or (
        isinstance(database_proxy.obj, SqliteDatabase)
        and str(error).lower() in {"database is locked", "database table is locked"}
    )


def retry_contention(operation):
    """Retry a whole rolled-back queue operation, never individual writes."""
    for attempt in range(3):
        try:
            return operation()
        except OperationalError as error:
            if not transient_database_error(error) or attempt == 2:
                raise
            time.sleep(random.uniform(0.02, 0.06) * 2**attempt)


def claim_job(owner):
    """Claim one due job or reclaim an expired lease, locking only queue rows."""

    def claim():
        with write_transaction():
            now = utc_now()
            query = (
                ChangeJob.select()
                .where(
                    (
                        (ChangeJob.state == "pending")
                        & (ChangeJob.next_attempt_at <= now)
                    )
                    | (
                        (ChangeJob.state == "running")
                        & (ChangeJob.lease_expires_at <= now)
                    )
                )
                .order_by(ChangeJob.next_attempt_at, ChangeJob.id)
            )
            if not isinstance(database_proxy.obj, SqliteDatabase):
                query = query.for_update("FOR UPDATE SKIP LOCKED")
            job = query.first()
            if job is None:
                return None
            now = utc_now()
            attempts = (
                job.attempts
                if job.claimed_generation == job.requested_generation
                else 0
            )
            settings = get_settings()
            if attempts >= settings.change_worker_max_attempts:
                ChangeJob.update(
                    state="dead",
                    last_error_class="attempts_exhausted",
                    lease_token=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                ).where(ChangeJob.id == job.id).execute()
                return None
            ChangeJob.update(
                state="running",
                claimed_generation=job.requested_generation,
                lease_owner=owner,
                lease_token=uuid.uuid4(),
                lease_expires_at=now
                + timedelta(seconds=settings.change_worker_lease_seconds),
                attempts=attempts + 1,
                updated_at=now,
            ).where(ChangeJob.id == job.id).execute()
            result = ChangeJob.get_by_id(job.id)
            result.reclaimed = job.state == "running"
            return result

    return retry_contention(claim)


def lease_predicate(claim, *, current_generation=True):
    """Fence by token, generation and wall-clock expiry, including renewals."""
    predicate = (
        (ChangeJob.id == claim.id)
        & (ChangeJob.state == "running")
        & (ChangeJob.lease_token == claim.lease_token)
        & (ChangeJob.claimed_generation == claim.claimed_generation)
        & (ChangeJob.lease_expires_at > utc_now())
    )
    if current_generation:
        predicate &= ChangeJob.requested_generation == claim.claimed_generation
    return predicate


def renew_lease(claim):
    """A replaced, expired or superseded claim cannot renew its lease."""
    with write_transaction():
        lock_claim(claim)
        changed = (
            ChangeJob.update(
                lease_expires_at=utc_now()
                + timedelta(seconds=get_settings().change_worker_lease_seconds),
                updated_at=utc_now(),
            )
            .where(lease_predicate(claim))
            .execute()
        )
        if changed != 1:
            raise LostChangeLease()


def lock_claim(claim, *, current_generation=True):
    """Take the queue lock last, after all domain locks used for publication."""
    if not database_proxy.in_transaction():
        raise RuntimeError("Claim publication requires the caller's transaction")
    query = ChangeJob.select().where(
        lease_predicate(claim, current_generation=current_generation)
    )
    if not isinstance(database_proxy.obj, SqliteDatabase):
        query = query.for_update()
    current = query.first()
    # The SELECT may have waited for another transaction. Its original time
    # predicate does not establish that the lease is still live after the wait.
    if current is None or current.lease_expires_at <= utc_now():
        raise LostChangeLease()


def finish_claim(claim, *, cursor=None, delay=None, stamp=None, error_class=None):
    """Acknowledge or checkpoint atomically with the caller's domain writes."""
    if not database_proxy.in_transaction():
        raise RuntimeError("Claim completion requires the caller's transaction")
    lock_claim(claim)
    values = {
        "state": "done" if delay is None else "pending",
        "cursor": cursor,
        "next_attempt_at": utc_now() + timedelta(seconds=delay or 0),
        "lease_owner": None,
        "lease_token": None,
        "lease_expires_at": None,
        "attempts": 0,
        "last_error_class": error_class,
        "updated_at": utc_now(),
    }
    if delay is None:
        values["completed_generation"] = claim.claimed_generation
    if stamp:
        values.update(stamp)
    if ChangeJob.update(**values).where(lease_predicate(claim)).execute() != 1:
        raise LostChangeLease()


def release_stale_claim(claim):
    """Retain a newer request; a former owner cannot affect a replacement lease."""
    with write_transaction():
        try:
            lock_claim(claim, current_generation=False)
        except LostChangeLease:
            return False
        return (
            ChangeJob.update(
                state="pending",
                cursor=None,
                attempts=0,
                next_attempt_at=utc_now(),
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                updated_at=utc_now(),
            )
            .where(lease_predicate(claim, current_generation=False))
            .execute()
            == 1
        )


def fail_claim(claim, *, transient):
    """Persist bounded backoff or dead state without losing newer generations."""
    with write_transaction():
        query = ChangeJob.select().where(
            lease_predicate(claim, current_generation=False)
        )
        if not isinstance(database_proxy.obj, SqliteDatabase):
            query = query.for_update()
        current = query.first()
        if current is None:
            return False
        if current.requested_generation != claim.claimed_generation:
            return release_stale_claim(claim)
        settings = get_settings()
        retry = transient and current.attempts < settings.change_worker_max_attempts
        delay = min(
            settings.change_worker_retry_max_seconds,
            settings.change_worker_retry_base_seconds
            * 2 ** min(current.attempts - 1, 16),
        )
        delay = random.uniform(delay / 2, delay)
        return (
            ChangeJob.update(
                state="pending" if retry else "dead",
                next_attempt_at=utc_now() + timedelta(seconds=delay),
                last_error_class="transient_database"
                if transient
                else "internal_error",
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                updated_at=utc_now(),
            )
            .where(lease_predicate(claim))
            .execute()
            == 1
        )


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
