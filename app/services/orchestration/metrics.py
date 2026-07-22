"""Operational disposition metrics for Event Orchestration."""

from __future__ import annotations

from typing import Optional

from peewee import fn

from app.modules.db.models import (
    AutomationExecution,
    OrchestrationExecution,
    PendingOrchestratedEvent,
)
from app.settings import Config


DISPOSITIONS = ("process", "suppress", "pause", "drop")
WEBHOOK_STATUSES = ("pending", "running", "succeeded", "failed", "cancelled")
PENDING_STATUSES = (
    "pending",
    "activating",
    "failed",
    "activated",
    "resolved",
    "cancelled",
)


def _count_by(query, model, field, known_values):
    result = {value: 0 for value in known_values}
    for row in query.select(field, fn.COUNT(model.id).alias("row_count")).group_by(field):
        value = getattr(row, field.name, None)
        if value is None:
            value = "unknown"
        result[value] = int(getattr(row, "row_count", 0) or 0)
    return result


def get_orchestration_disposition_metrics(
    *,
    group_id: Optional[int] = None,
    since=None,
    until=None,
):
    """Return portable DB-backed counts for disposition and pause states."""
    executions = OrchestrationExecution.select()
    pending = PendingOrchestratedEvent.select()
    webhooks = AutomationExecution.select()

    if group_id is not None:
        executions = executions.where(OrchestrationExecution.group == group_id)
        pending = pending.where(PendingOrchestratedEvent.group == group_id)
        webhooks = webhooks.where(AutomationExecution.group == group_id)
    if since is not None:
        executions = executions.where(OrchestrationExecution.created_at >= since)
        pending = pending.where(PendingOrchestratedEvent.created_at >= since)
        webhooks = webhooks.where(AutomationExecution.created_at >= since)
    if until is not None:
        executions = executions.where(OrchestrationExecution.created_at < until)
        pending = pending.where(PendingOrchestratedEvent.created_at < until)
        webhooks = webhooks.where(AutomationExecution.created_at < until)

    dispositions = _count_by(
        executions,
        OrchestrationExecution,
        OrchestrationExecution.disposition,
        DISPOSITIONS,
    )
    pending_statuses = _count_by(
        pending,
        PendingOrchestratedEvent,
        PendingOrchestratedEvent.status,
        PENDING_STATUSES,
    )

    webhook_statuses = _count_by(
        webhooks,
        AutomationExecution,
        AutomationExecution.status,
        WEBHOOK_STATUSES,
    )

    return {
        "executions_total": sum(dispositions.values()),
        "dispositions": dispositions,
        "pending_events_total": sum(pending_statuses.values()),
        "pending_statuses": pending_statuses,
        "webhook_executions_total": sum(webhook_statuses.values()),
        "webhook_statuses": webhook_statuses,
        "dropped_trace_retention_days": int(
            getattr(Config, "ORCHESTRATION_DROPPED_TRACE_RETENTION_DAYS", 7)
        ),
    }


__all__ = ["get_orchestration_disposition_metrics"]
