"""Shared safety helpers for soft-delete lifecycle transitions.

These helpers only depend on database models so repository modules can use them
without creating circular imports. Historical rows are preserved; only active
or queued operational state is stopped.
"""

from app.modules.common import utc_now
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AutomationExecution,
    BrowserPushActionToken,
    BrowserPushSubscription,
    IncidentResponder,
    IncidentStakeholder,
    OrchestrationExecution,
    PendingOrchestratedEvent,
    ServiceOwner,
    SsoGroupMapping,
    UserNotificationDelivery,
    UserNotificationRule,
)


_PENDING_DELIVERY_STATUSES = ("pending", "processing")
_PENDING_ORCHESTRATION_STATUSES = ("pending", "failed", "activating")
_PENDING_AUTOMATION_STATUSES = ("pending", "running")


def deactivate_user_runtime(user_id, *, now=None, reason="user_deleted"):
    """Disable personal notification/access state owned by a deleted user."""
    now = now or utc_now()

    UserNotificationRule.update(
        enabled=False,
        deleted=True,
        deleted_at=now,
        updated_at=now,
    ).where(
        (UserNotificationRule.user == user_id)
        & (UserNotificationRule.deleted == False)  # noqa: E712
    ).execute()

    BrowserPushSubscription.update(
        enabled=False,
        deleted=True,
        deleted_at=now,
        updated_at=now,
    ).where(
        (BrowserPushSubscription.user == user_id)
        & (BrowserPushSubscription.deleted == False)  # noqa: E712
    ).execute()

    # Action tokens are short-lived credentials rather than history.
    BrowserPushActionToken.delete().where(
        BrowserPushActionToken.user == user_id
    ).execute()

    UserNotificationDelivery.update(
        status="skipped",
        provider_status="skipped",
        last_error=reason,
        updated_at=now,
    ).where(
        (UserNotificationDelivery.user == user_id)
        & (UserNotificationDelivery.status.in_(_PENDING_DELIVERY_STATUSES))
    ).execute()

    ServiceOwner.update(active=False).where(
        ServiceOwner.user == user_id
    ).execute()

    IncidentStakeholder.update(
        active=False,
        updated_at=now,
    ).where(
        (IncidentStakeholder.user == user_id)
        & (IncidentStakeholder.active == True)  # noqa: E712
    ).execute()

    # A deleted user cannot accept an outstanding responder request. Accepted
    # rows remain historical incident state.
    IncidentResponder.update(
        status="expired",
        notification_status="skipped",
        notification_error=reason,
        response_message="Responder user was deleted",
        responded_at=now,
        updated_at=now,
    ).where(
        (IncidentResponder.target_user == user_id)
        & (IncidentResponder.status == "requested")
    ).execute()


def resolve_alert_groups_by_ids(group_ids, *, now=None, reason="resource_deleted"):
    """Resolve selected alert groups without triggering new notifications."""
    group_ids = [int(value) for value in set(group_ids or []) if value]
    if not group_ids:
        return 0
    now = now or utc_now()

    Alert.update(
        previous_status=Alert.status,
        status="resolved",
        resolved_at=now,
        next_escalation_at=None,
    ).where(
        (Alert.group.in_(group_ids))
        & (Alert.status != "resolved")
    ).execute()

    return AlertGroup.update(
        previous_status=AlertGroup.status,
        status="resolved",
        resolved_at=now,
        next_escalation_at=None,
        notification_due_at=None,
        notification_pending=False,
        notification_reason=reason,
        firing_count=0,
        acknowledged_count=0,
        silenced_count=0,
        resolved_count=AlertGroup.alert_count,
        updated_at=now,
    ).where(
        (AlertGroup.id.in_(group_ids))
        & (~AlertGroup.status.in_(("resolved", "merged")))
    ).execute()


def resolve_team_runtime_alerts(team_id, *, now=None):
    """Make unresolved alerts owned by a deleted team terminal.

    This prevents old incidents from re-entering reminder/escalation processing
    if a team with the same row is restored later.
    """
    now = now or utc_now()

    Alert.update(
        previous_status=Alert.status,
        status="resolved",
        resolved_at=now,
        next_escalation_at=None,
    ).where(
        (Alert.team == team_id)
        & (Alert.status != "resolved")
    ).execute()

    AlertGroup.update(
        previous_status=AlertGroup.status,
        status="resolved",
        resolved_at=now,
        next_escalation_at=None,
        notification_due_at=None,
        notification_pending=False,
        notification_reason="team_deleted",
        firing_count=0,
        acknowledged_count=0,
        silenced_count=0,
        resolved_count=AlertGroup.alert_count,
        updated_at=now,
    ).where(
        (AlertGroup.team == team_id)
        & (~AlertGroup.status.in_(("resolved", "merged")))
    ).execute()


def cancel_pending_orchestration_work(
    *,
    group_id=None,
    service_id=None,
    route_id=None,
    orchestration_ids=None,
    action_ids=None,
    now=None,
    reason="resource_deleted",
):
    """Cancel queued orchestration work affected by a deleted resource."""
    now = now or utc_now()

    pending_query = PendingOrchestratedEvent.status.in_(_PENDING_ORCHESTRATION_STATUSES)
    if group_id is not None:
        pending_query &= PendingOrchestratedEvent.group == group_id
    if service_id is not None:
        pending_query &= PendingOrchestratedEvent.service == service_id
    if route_id is not None:
        pending_query &= PendingOrchestratedEvent.route == route_id
    if orchestration_ids is not None:
        orchestration_ids = list(orchestration_ids)
        if orchestration_ids:
            pending_query &= PendingOrchestratedEvent.orchestration.in_(orchestration_ids)
        else:
            pending_query &= PendingOrchestratedEvent.id == -1

    PendingOrchestratedEvent.update(
        status="cancelled",
        active_key=None,
        last_error=reason,
        claim_token=None,
        claimed_at=None,
        next_attempt_at=None,
        resolved_at=now,
        updated_at=now,
    ).where(pending_query).execute()

    automation_query = AutomationExecution.status.in_(_PENDING_AUTOMATION_STATUSES)
    if group_id is not None:
        automation_query &= AutomationExecution.group == group_id
    if action_ids is not None:
        action_ids = list(action_ids)
        if action_ids:
            automation_query &= AutomationExecution.action.in_(action_ids)
        else:
            automation_query &= AutomationExecution.id == -1
    if orchestration_ids is not None:
        orchestration_ids = list(orchestration_ids)
        if orchestration_ids:
            execution_ids = OrchestrationExecution.select(OrchestrationExecution.id).where(
                OrchestrationExecution.orchestration.in_(orchestration_ids)
            )
            automation_query &= AutomationExecution.orchestration_execution.in_(execution_ids)
        else:
            automation_query &= AutomationExecution.id == -1

    # Service/route are represented on the alert group attached to an
    # automation execution. This also catches queued work created before the
    # soft-delete cascade was introduced.
    if service_id is not None or route_id is not None:
        group_ids = AlertGroup.select(AlertGroup.id)
        if service_id is not None:
            group_ids = group_ids.where(AlertGroup.service == service_id)
        if route_id is not None:
            group_ids = group_ids.where(AlertGroup.route == route_id)
        automation_query &= AutomationExecution.alert_group_id.in_(group_ids)

    AutomationExecution.update(
        status="cancelled",
        error_safe=reason,
        claim_token=None,
        claimed_at=None,
        next_attempt_at=None,
        finished_at=now,
    ).where(automation_query).execute()


def deactivate_sso_mappings(*, group_id=None, team_id=None):
    """Disable mappings that target a deleted IncidentRelay scope."""
    query = SsoGroupMapping.active == True  # noqa: E712
    if group_id is not None:
        query &= SsoGroupMapping.incidentrelay_group == group_id
    if team_id is not None:
        query &= SsoGroupMapping.incidentrelay_team == team_id
    if group_id is None and team_id is None:
        return 0
    return SsoGroupMapping.update(active=False).where(query).execute()
