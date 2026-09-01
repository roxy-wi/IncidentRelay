"""Persistence and activation workflow for paused orchestration events."""

from __future__ import annotations

import copy
import hashlib
import logging
import uuid
from datetime import timedelta
from typing import Any, Dict, Mapping, Optional

from peewee import IntegrityError

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db.models import (
    EventOrchestration,
    EventOrchestrationVersion,
    OrchestrationExecution,
    PendingOrchestratedEvent,
)
from app.modules.redaction import redact_secrets
from app.services.alerts.explain import (
    AlertExplainTrace,
    resolve_alert_explain_trace_level,
)
from app.services.alerts.result import AlertProcessingResult
from app.services.orchestration.runtime import (
    RuntimeResult,
    attach_runtime_executions,
    restore_runtime_result,
)
from app.services.validation import make_json_safe
from app.services.orchestration.webhooks import cleanup_webhook_executions
from app.settings import Config

logger = logging.getLogger("oncall.orchestration.pending")

TERMINAL_STATUSES = frozenset({"activated", "resolved", "cancelled"})


def pending_active_key(group_id: int, source: str, dedup_key: str) -> str:
    material = f"{int(group_id)}\x1f{source or ''}\x1f{dedup_key or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _event_for_storage(alert_data: Mapping[str, Any]) -> Dict[str, Any]:
    value = copy.deepcopy(dict(alert_data or {}))
    value.pop("raw", None)
    for key in tuple(value):
        if str(key).startswith("_orchestration_"):
            value.pop(key, None)
    return make_json_safe(value)


def _terminal_event_snapshot(value: Mapping[str, Any]) -> Dict[str, Any]:
    event = dict(value or {})
    return {
        key: make_json_safe(event.get(key))
        for key in (
            "source",
            "external_id",
            "dedup_key",
            "group_key",
            "title",
            "severity",
            "status",
            "labels",
        )
        if key in event
    }


def _runtime_context(runtime: RuntimeResult, previous=None) -> Dict[str, Any]:
    previous = dict(previous or {})
    updates = list(previous.get("updates") or [])[-49:]
    updates.append(
        {
            "at": utc_now().isoformat(),
            "execution_ids": list(runtime.execution_ids),
            "disposition": runtime.disposition,
        }
    )
    return redact_secrets(
        make_json_safe(
            {
                "runtime": runtime.to_dict(),
                "updates": updates,
            }
        )
    )


def _source_models(runtime: RuntimeResult):
    orchestration_id = runtime.disposition_orchestration_id
    version_id = runtime.disposition_version_id
    if not orchestration_id or not version_id:
        raise ValueError("pause disposition is missing orchestration provenance")
    orchestration = EventOrchestration.get_by_id(orchestration_id)
    version = EventOrchestrationVersion.get_by_id(version_id)
    return orchestration, version


def store_paused_event(
    alert_data: Mapping[str, Any],
    runtime: RuntimeResult,
    *,
    route=None,
    service=None,
    trace=None,
    now=None,
) -> PendingOrchestratedEvent:
    """Create or refresh the one active paused row for an event fingerprint."""
    now = now or utc_now()
    group_id = runtime.group_id
    if group_id is None and route is not None:
        group_id = getattr(getattr(route, "team", None), "group_id", None)
    if group_id is None:
        raise ValueError("paused event requires a group")

    source = str(alert_data.get("source") or "")
    dedup_key = str(alert_data.get("dedup_key") or "")
    if not source or not dedup_key:
        raise ValueError("paused event requires source and dedup_key")

    seconds = int(runtime.pause_seconds or 0)
    if seconds <= 0:
        raise ValueError("paused event requires a positive pause duration")

    orchestration, version = _source_models(runtime)
    key = pending_active_key(group_id, source, dedup_key)
    requested_activation_at = now + timedelta(seconds=seconds)
    stored_event = _event_for_storage(alert_data)
    route_id = getattr(route or runtime.route, "id", None)
    service_id = getattr(service or runtime.service, "id", None)
    integration_name = alert_data.get("integration_name") or source

    row = None
    for _attempt in range(4):
        with db.atomic():
            current = PendingOrchestratedEvent.get_or_none(
                PendingOrchestratedEvent.active_key == key
            )

            if current is None:
                try:
                    # The nested atomic block is a savepoint on PostgreSQL, so a
                    # concurrent unique-key insert does not poison the outer transaction.
                    with db.atomic():
                        row = PendingOrchestratedEvent.create(
                            group=group_id,
                            orchestration=orchestration.id,
                            version=version.id,
                            route=route_id,
                            service=service_id,
                            source=source,
                            integration_name=integration_name,
                            dedup_key=dedup_key,
                            active_key=key,
                            normalized_event_json=stored_event,
                            context_json=_runtime_context(runtime),
                            activation_at=requested_activation_at,
                            status="pending",
                            created_at=now,
                            updated_at=now,
                        )
                except IntegrityError:
                    row = None
                if row is not None:
                    break
                continue

            context_json = _runtime_context(runtime, current.context_json)

            if current.status == "activating":
                # Never clear or replace a live claim. Refresh the payload for
                # observability, while the claimed worker completes atomically.
                updated = (
                    PendingOrchestratedEvent.update(
                        orchestration=orchestration.id,
                        version=version.id,
                        route=route_id,
                        service=service_id,
                        integration_name=integration_name,
                        normalized_event_json=stored_event,
                        context_json=context_json,
                        updated_at=now,
                    )
                    .where(
                        (PendingOrchestratedEvent.id == current.id)
                        & (PendingOrchestratedEvent.active_key == key)
                        & (PendingOrchestratedEvent.status == "activating")
                        & (PendingOrchestratedEvent.claim_token == current.claim_token)
                    )
                    .execute()
                )
            else:
                activation_at = requested_activation_at
                if runtime.pause_retrigger != "reset":
                    activation_at = current.activation_at
                updated = (
                    PendingOrchestratedEvent.update(
                        orchestration=orchestration.id,
                        version=version.id,
                        route=route_id,
                        service=service_id,
                        integration_name=integration_name,
                        normalized_event_json=stored_event,
                        context_json=context_json,
                        activation_at=activation_at,
                        status="pending",
                        attempts=0,
                        last_error=None,
                        claim_token=None,
                        claimed_at=None,
                        next_attempt_at=None,
                        resolved_at=None,
                        activated_at=None,
                        updated_at=now,
                    )
                    .where(
                        (PendingOrchestratedEvent.id == current.id)
                        & (PendingOrchestratedEvent.active_key == key)
                        & PendingOrchestratedEvent.status.in_(("pending", "failed"))
                    )
                    .execute()
                )

            if updated == 1:
                row = PendingOrchestratedEvent.get_by_id(current.id)
                break

    if row is None:
        raise RuntimeError("paused event changed concurrently; retry the request")

    if trace is not None:
        trace.step(
            "orchestration",
            "orchestration_event_paused",
            "success",
            "Event activation paused",
            runtime.disposition_reason,
            pending_event_id=row.id,
            activation_at=row.activation_at.isoformat(),
            pause_seconds=seconds,
            retrigger=runtime.pause_retrigger,
            activation_in_progress=row.status == "activating",
        )
    return row

def resolve_pending_event(
    *,
    group_id: int,
    source: str,
    dedup_key: str,
    trace=None,
    now=None,
) -> Optional[PendingOrchestratedEvent]:
    """Resolve a paused trigger before its activation transaction commits."""
    now = now or utc_now()
    key = pending_active_key(group_id, source, dedup_key)

    with db.atomic():
        row = PendingOrchestratedEvent.get_or_none(
            PendingOrchestratedEvent.active_key == key
        )
        if row is None:
            return None

        updated = (
            PendingOrchestratedEvent.update(
                status="resolved",
                active_key=None,
                resolved_at=now,
                updated_at=now,
                claim_token=None,
                claimed_at=None,
                next_attempt_at=None,
                normalized_event_json=_terminal_event_snapshot(
                    row.normalized_event_json or {}
                ),
            )
            .where(
                (PendingOrchestratedEvent.id == row.id)
                & (PendingOrchestratedEvent.active_key == key)
                & PendingOrchestratedEvent.status.in_(("pending", "failed", "activating"))
            )
            .execute()
        )
        if updated != 1:
            return None
        row = PendingOrchestratedEvent.get_by_id(row.id)

    if trace is not None:
        trace.step(
            "orchestration",
            "orchestration_pause_resolved_before_activation",
            "success",
            "Paused event resolved before activation",
            "No alert or incident was created.",
            pending_event_id=row.id,
        )
    return row

def _claim_one(row_id: int, *, now) -> Optional[PendingOrchestratedEvent]:
    token = uuid.uuid4().hex
    updated = (
        PendingOrchestratedEvent.update(
            status="activating",
            claim_token=token,
            claimed_at=now,
            updated_at=now,
        )
        .where(
            (PendingOrchestratedEvent.id == row_id)
            & (PendingOrchestratedEvent.status == "pending")
        )
        .execute()
    )
    if updated != 1:
        return None
    return PendingOrchestratedEvent.get(
        (PendingOrchestratedEvent.id == row_id)
        & (PendingOrchestratedEvent.claim_token == token)
    )


def _requeue_stale_claims(now) -> int:
    cutoff = now - timedelta(
        seconds=int(getattr(Config, "ORCHESTRATION_PENDING_CLAIM_TTL_SECONDS", 300))
    )
    return (
        PendingOrchestratedEvent.update(
            status="pending",
            claim_token=None,
            claimed_at=None,
            updated_at=now,
        )
        .where(
            (PendingOrchestratedEvent.status == "activating")
            & (PendingOrchestratedEvent.claimed_at <= cutoff)
        )
        .execute()
    )


def _activation_runtime(row: PendingOrchestratedEvent) -> RuntimeResult:
    context = row.context_json or {}
    runtime = restore_runtime_result(context.get("runtime") or {})
    runtime.disposition = "process"
    runtime.disposition_reason = None
    runtime.pause_seconds = None
    runtime.pause_retrigger = "preserve"
    return runtime


def _mark_activation_failed(row, exc, *, now):
    attempts = int(row.attempts or 0) + 1
    max_attempts = int(getattr(Config, "ORCHESTRATION_PENDING_MAX_ATTEMPTS", 5))
    error = str(redact_secrets(exc))[:2048]
    if attempts >= max_attempts:
        status = "failed"
        next_attempt_at = None
    else:
        status = "pending"
        base = int(getattr(Config, "ORCHESTRATION_PENDING_RETRY_BASE_SECONDS", 30))
        next_attempt_at = now + timedelta(seconds=min(base * (2 ** (attempts - 1)), 3600))

    PendingOrchestratedEvent.update(
        status=status,
        attempts=attempts,
        last_error=error,
        claim_token=None,
        claimed_at=None,
        next_attempt_at=next_attempt_at,
        updated_at=now,
    ).where(
        (PendingOrchestratedEvent.id == row.id)
        & (PendingOrchestratedEvent.status == "activating")
        & (PendingOrchestratedEvent.claim_token == row.claim_token)
    ).execute()


def _activate_claimed(
    row: PendingOrchestratedEvent,
    *,
    now,
) -> Optional[AlertProcessingResult]:
    from app.services.alerts.lifecycle import _upsert_alert

    # This write acquires a row lock on PostgreSQL and the write lock on
    # SQLite. Resolve requests either win before it or wait until the alert
    # and pending-state transition commit together.
    with db.atomic():
        locked = (
            PendingOrchestratedEvent.update(
                claimed_at=now,
                updated_at=now,
            )
            .where(
                (PendingOrchestratedEvent.id == row.id)
                & (PendingOrchestratedEvent.status == "activating")
                & (PendingOrchestratedEvent.claim_token == row.claim_token)
            )
            .execute()
        )
        if locked != 1:
            return None

        row = PendingOrchestratedEvent.get_by_id(row.id)
        alert_data = copy.deepcopy(row.normalized_event_json or {})
        runtime = _activation_runtime(row)
        trace = AlertExplainTrace.start_buffered(alert_data)
        trace.apply_level(
            resolve_alert_explain_trace_level(runtime.trace_level)
        )
        trace.step(
            "orchestration",
            "orchestration_pause_activated",
            "success",
            "Paused event activation started",
            pending_event_id=row.id,
            scheduled_activation_at=row.activation_at.isoformat(),
        )

        result = _upsert_alert(alert_data, trace, runtime=runtime)
        if result.group is None or result.alert is None:
            raise RuntimeError(
                result.reason or f"paused event activation ended with {result.outcome}"
            )

        attach_runtime_executions(runtime, group=result.group, alert=result.alert)
        updated = (
            PendingOrchestratedEvent.update(
                status="activated",
                active_key=None,
                activated_at=now,
                normalized_event_json=_terminal_event_snapshot(alert_data),
                claim_token=None,
                claimed_at=None,
                next_attempt_at=None,
                last_error=None,
                updated_at=now,
            )
            .where(
                (PendingOrchestratedEvent.id == row.id)
                & (PendingOrchestratedEvent.status == "activating")
                & (PendingOrchestratedEvent.claim_token == row.claim_token)
            )
            .execute()
        )
        if updated != 1:
            raise RuntimeError("paused event activation claim was lost")
        return result

def process_due_pending_events(limit=100, *, now=None):
    """Activate due paused events with atomic claims and bounded retries."""
    now = now or utc_now()
    result = {"processed": 0, "activated": 0, "failed": 0, "requeued": 0}
    result["requeued"] = _requeue_stale_claims(now)

    rows = list(
        PendingOrchestratedEvent.select(PendingOrchestratedEvent.id)
        .where(
            (PendingOrchestratedEvent.status == "pending")
            & (PendingOrchestratedEvent.activation_at <= now)
            & (
                PendingOrchestratedEvent.next_attempt_at.is_null(True)
                | (PendingOrchestratedEvent.next_attempt_at <= now)
            )
        )
        .order_by(
            PendingOrchestratedEvent.activation_at.asc(),
            PendingOrchestratedEvent.id.asc(),
        )
        .limit(int(limit))
    )

    for candidate in rows:
        claimed = _claim_one(candidate.id, now=now)
        if claimed is None:
            continue
        result["processed"] += 1
        try:
            activated = _activate_claimed(claimed, now=utc_now())
            if activated is not None:
                result["activated"] += 1
        except Exception as exc:
            logger.exception(
                "paused orchestration event activation failed",
                extra={"extra": {"pending_event_id": claimed.id}},
            )
            _mark_activation_failed(claimed, exc, now=utc_now())
            result["failed"] += 1
    return result


def retry_failed_pending_event(pending_event_id: int, *, now=None):
    now = now or utc_now()
    updated = (
        PendingOrchestratedEvent.update(
            status="pending",
            attempts=0,
            last_error=None,
            claim_token=None,
            claimed_at=None,
            next_attempt_at=now,
            activation_at=now,
            updated_at=now,
        )
        .where(
            (PendingOrchestratedEvent.id == pending_event_id)
            & (PendingOrchestratedEvent.status == "failed")
        )
        .execute()
    )
    return updated == 1


def cleanup_orchestration_retention(*, now=None, execution_retention_days=None):
    now = now or utc_now()
    executions_deleted = (
        OrchestrationExecution.delete()
        .where(
            OrchestrationExecution.expires_at.is_null(False)
            & (OrchestrationExecution.expires_at <= now)
        )
        .execute()
    )

    if execution_retention_days is None:
        execution_retention_days = getattr(
            Config,
            "RETENTION_ORCHESTRATION_EXECUTION_DAYS",
            0,
        )
    execution_retention_days = int(execution_retention_days)
    if execution_retention_days < 0:
        raise ValueError(
            "execution_retention_days must be greater than or equal to 0"
        )
    if execution_retention_days > 0:
        execution_cutoff = now - timedelta(days=execution_retention_days)
        executions_deleted += (
            OrchestrationExecution.delete()
            .where(OrchestrationExecution.created_at < execution_cutoff)
            .execute()
        )

    retention_days = int(
        getattr(Config, "ORCHESTRATION_PENDING_EVENT_RETENTION_DAYS", 30)
    )
    cutoff = now - timedelta(days=retention_days)
    pending_deleted = (
        PendingOrchestratedEvent.delete()
        .where(
            PendingOrchestratedEvent.status.in_(tuple(TERMINAL_STATUSES))
            & (PendingOrchestratedEvent.updated_at <= cutoff)
        )
        .execute()
    )
    webhook_executions_deleted = cleanup_webhook_executions(now=now)
    return {
        "executions_deleted": executions_deleted,
        "pending_events_deleted": pending_deleted,
        "webhook_executions_deleted": webhook_executions_deleted,
    }


__all__ = [
    "cleanup_orchestration_retention",
    "pending_active_key",
    "process_due_pending_events",
    "resolve_pending_event",
    "retry_failed_pending_event",
    "store_paused_event",
]
