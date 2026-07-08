from app.modules.db import services_repo, maintenance_repo
from app.services.serializers.common import serialize_utc_datetime, attach_team_permissions, attach_group_permissions, \
    serialize_local_datetime
from app.services.serializers.users import serialize_user_short


def serialize_service_short(service):
    """Serialize a compact service object."""
    if not service:
        return None

    return {
        "id": service.id,
        "slug": service.slug,
        "name": service.name,
        "status": service.status,
        "criticality": service.criticality,
        "environment": service.environment,
        "enabled": service.enabled,
    }


def serialize_service_readiness_state(state):
    """Serialize the current aggregated service readiness state."""

    if state is None:
        return None

    return {
        "status": state.status,
        "score": state.score,
        "standards_count": state.standards_count,
        "checks_count": state.checks_count,
        "failed_count": state.failed_count,
        "failed_required_count": state.failed_required_count,
        "failed_critical_count": state.failed_critical_count,
        "batch_uid": str(state.batch_uid),
        "evaluated_at": serialize_utc_datetime(state.evaluated_at),
    }


def serialize_service_readiness_check_result(result):
    """Serialize one readiness check result snapshot."""

    return {
        "id": result.id,
        "check_id": result.check_id,
        "check_uid": str(result.check_uid) if result.check_uid else None,
        "check_slug": result.check_slug,
        "check_name": result.check_name,
        "check_type": result.check_type,
        "status": result.status,
        "weight": result.weight,
        "severity": result.severity,
        "required": result.required,
        "message": result.message,
        "details": result.details or {},
        "evaluated_at": serialize_utc_datetime(result.evaluated_at),
    }


def serialize_service_readiness_evaluation(evaluation, results=None):
    """Serialize one standard evaluation."""

    standard = evaluation.standard if evaluation.standard_id else None
    actor_user = evaluation.actor_user if evaluation.actor_user_id else None

    return {
        "id": evaluation.id,
        "uid": str(evaluation.uid),
        "batch_uid": str(evaluation.batch_uid),
        "service_id": evaluation.service_id,
        "standard": {
            "id": standard.id,
            "uid": str(standard.uid),
            "slug": standard.slug,
            "name": standard.name,
            "enabled": standard.enabled,
        } if standard else None,
        "status": evaluation.status,
        "score": evaluation.score,
        "passed_weight": evaluation.passed_weight,
        "total_weight": evaluation.total_weight,
        "checks_count": evaluation.checks_count,
        "failed_count": evaluation.failed_count,
        "failed_required_count": evaluation.failed_required_count,
        "failed_critical_count": evaluation.failed_critical_count,
        "trigger": evaluation.trigger,
        "actor_user_id": actor_user.id if actor_user else None,
        "evaluated_at": serialize_utc_datetime(evaluation.evaluated_at),
        "results": [
            serialize_service_readiness_check_result(result)
            for result in results or []
        ],
    }


def serialize_service_readiness(state, evaluations=None, results_by_evaluation=None):
    """Serialize the current readiness batch for a service."""

    results_by_evaluation = results_by_evaluation or {}

    return {
        "state": serialize_service_readiness_state(state),
        "evaluations": [
            serialize_service_readiness_evaluation(
                evaluation,
                results=results_by_evaluation.get(evaluation.id, []),
            )
            for evaluation in evaluations or []
        ],
    }


def serialize_service(service, current_user=None, readiness_state=None):
    """Serialize a service."""
    team = service.team if service.team_id else None
    group = service.group if service.group_id else None
    notification_policy = (
        service.notification_policy
        if getattr(service, "notification_policy_id", None)
        else None
    )

    priority_policy = (
        service.priority_policy
        if getattr(service, "priority_policy_id", None)
        else None
    )

    data = {
        "id": service.id,
        "uid": str(service.uid),
        "group_id": group.id if group else None,
        "group_slug": group.slug if group else None,
        "group_name": group.name if group else None,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,

        "slug": service.slug,
        "name": service.name,
        "description": service.description,
        "kind": service.kind,
        "lifecycle": service.lifecycle,

        "service_type": service.service_type,
        "environment": service.environment,
        "criticality": service.criticality,
        "tier": service.tier,

        "status": service.status,
        "status_source": service.status_source,
        "status_message": service.status_message,
        "status_updated_at": serialize_utc_datetime(service.status_updated_at),

        "default_rotation_id": (
            service.default_rotation.id
            if getattr(service, "default_rotation_id", None)
            else None
        ),
        "default_rotation_name": (
            service.default_rotation.name
            if getattr(service, "default_rotation_id", None)
            else None
        ),
        "default_escalation_policy_id": (
            service.default_escalation_policy.id
            if getattr(service, "default_escalation_policy_id", None)
            else None
        ),
        "default_escalation_policy_name": (
            service.default_escalation_policy.name
            if getattr(service, "default_escalation_policy_id", None)
            else None
        ),

        "notification_policy_id": (
            notification_policy.id if notification_policy else None
        ),
        "notification_policy_name": (
            notification_policy.name if notification_policy else None
        ),
        "priority_policy_id": (
            priority_policy.id if priority_policy else None
        ),
        "priority_policy_name": (
            priority_policy.name if priority_policy else None
        ),

        "labels": service.labels or {},
        "tags": service.tags or [],
        "metadata": service.metadata or {},

        "enabled": service.enabled,
        "public": service.public,
        "public_name": service.public_name,
        "public_description": service.public_description,
        "public_order": service.public_order,

        "created_at": serialize_utc_datetime(service.created_at),
        "updated_at": serialize_utc_datetime(service.updated_at),
        "readiness": serialize_service_readiness_state(readiness_state),
        "active_maintenance": serialize_active_maintenance_for_scope(
            group_id=service.team.group_id if service.team_id and service.team else None,
            team_id=service.team_id,
            service_id=service.id,
        ),
        "owners": [
            serialize_service_owner(owner, current_user)
            for owner in services_repo.list_service_owners(
                service.id,
                active_only=True,
            )
        ],
    }

    return attach_team_permissions(data, service.team_id, current_user)


def serialize_service_standard_check(check):
    """Serialize a service readiness standard check."""

    return {
        "id": check.id,
        "uid": str(check.uid),
        "standard_id": check.standard_id,
        "slug": check.slug,
        "name": check.name,
        "description": check.description,
        "check_type": check.check_type,
        "configuration": check.configuration or {},
        "weight": check.weight,
        "severity": check.severity,
        "required": check.required,
        "enabled": check.enabled,
        "position": check.position,
        "created_at": serialize_utc_datetime(check.created_at),
        "updated_at": serialize_utc_datetime(check.updated_at),
    }


def serialize_service_standard(standard, current_user=None, checks=None):
    """Serialize a service readiness standard."""

    group = standard.group if standard.group_id else None
    created_by = standard.created_by if standard.created_by_id else None

    data = {
        "id": standard.id,
        "uid": str(standard.uid),
        "group_id": group.id if group else None,
        "group_slug": group.slug if group else None,
        "group_name": group.name if group else None,
        "slug": standard.slug,
        "name": standard.name,
        "description": standard.description,
        "applies_to": standard.applies_to or {},
        "enabled": standard.enabled,
        "created_by": serialize_user_short(created_by),
        "created_at": serialize_utc_datetime(standard.created_at),
        "updated_at": serialize_utc_datetime(standard.updated_at),
    }

    if checks is not None:
        data["checks"] = [serialize_service_standard_check(check) for check in checks]
        data["checks_count"] = len(checks)

    return attach_group_permissions(data, standard.group_id, current_user)


def serialize_service_match_rule(rule, current_user=None):
    """Serialize a service match rule."""
    service = rule.service if rule.service_id else None
    route = rule.route if getattr(rule, "route_id", None) else None
    team = rule.team if rule.team_id else None
    matcher_preset = (
        rule.matcher_preset
        if getattr(rule, "matcher_preset_id", None)
        else None
    )

    data = {
        "id": rule.id,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,

        "route_id": route.id if route else None,
        "route_name": route.name if route else None,

        "service_id": service.id if service else None,
        "service_slug": service.slug if service else None,
        "service_name": service.name if service else None,

        "position": rule.position,
        "name": rule.name,
        "description": rule.description,
        "matcher_preset_id": matcher_preset.id if matcher_preset else None,
        "matcher_preset": {
            "id": matcher_preset.id,
            "name": matcher_preset.name,
            "version": matcher_preset.version,
            "enabled": matcher_preset.enabled,
        } if matcher_preset else None,
        "matchers": rule.matchers or {},
        "enabled": rule.enabled,

        "created_at": serialize_utc_datetime(rule.created_at),
        "updated_at": serialize_utc_datetime(rule.updated_at),
    }

    return attach_team_permissions(data, rule.team_id, current_user)


def serialize_service_link(link, current_user=None):
    """Serialize a service link."""
    service = link.service
    team = service.team if service else None

    data = {
        "id": link.id,

        "service_id": service.id if service else link.service_id,
        "service_name": service.name if service else None,
        "service_slug": service.slug if service else None,

        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,

        "link_type": link.link_type,
        "label": link.label,
        "url": link.url,
        "description": link.description,
        "priority": link.priority,
        "enabled": link.enabled,
        "created_at": serialize_utc_datetime(link.created_at),
        "updated_at": serialize_utc_datetime(link.updated_at),
    }

    return attach_team_permissions(
        data,
        team.id if team else None,
        current_user,
    )


def serialize_service_owner(owner, current_user=None):
    """Serialize a service owner."""
    service = owner.service
    user = owner.user

    return {
        "id": owner.id,
        "service_id": service.id if service else None,
        "team_id": service.team_id if service else None,
        "group_id": service.group_id if service else None,
        "user_id": user.id if user else None,
        "username": user.username if user else None,
        "user_email": user.email if user else None,
        "user_display_name": getattr(user, "display_name", None)
        if user
        else None,
        "role": owner.role,
        "active": owner.active,
        "notify_on_created": bool(getattr(owner, "notify_on_created", True)),
        "notify_on_priority_change": bool(getattr(owner, "notify_on_priority_change", True)),
        "notify_on_status_change": bool(getattr(owner, "notify_on_status_change", True)),
        "notify_on_resolved": bool(getattr(owner, "notify_on_resolved", True)),
        "notify_on_comment": bool(getattr(owner, "notify_on_comment", True)),
        "created_at": owner.created_at.isoformat()
        if owner.created_at
        else None,
    }


def serialize_service_runbook(runbook, current_user=None):
    """Serialize a service runbook."""
    service = runbook.service
    team = service.team if service else None
    matcher_preset = (
        runbook.matcher_preset
        if getattr(runbook, "matcher_preset_id", None)
        else None
    )

    data = {
        "id": runbook.id,

        "service_id": service.id if service else runbook.service_id,
        "service_name": service.name if service else None,
        "service_slug": service.slug if service else None,

        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,

        "title": runbook.title,
        "description": runbook.description,
        "url": runbook.url,
        "severity": runbook.severity,
        "matcher_preset_id": matcher_preset.id if matcher_preset else None,
        "matcher_preset": {
            "id": matcher_preset.id,
            "name": matcher_preset.name,
            "version": matcher_preset.version,
            "enabled": matcher_preset.enabled,
            "matchers": matcher_preset.matchers or {},
        } if matcher_preset else None,
        "matchers": runbook.matchers or {},
        "priority": runbook.priority,
        "enabled": runbook.enabled,
        "created_at": serialize_utc_datetime(runbook.created_at),
        "updated_at": serialize_utc_datetime(runbook.updated_at),
    }

    return attach_team_permissions(
        data,
        team.id if team else None,
        current_user,
    )


def serialize_service_sli(sli, current_user=None):
    """Serialize a Service Level Indicator."""
    service = sli.service if getattr(sli, "service_id", None) else None
    team = service.team if service and getattr(service, "team_id", None) else None

    data = {
        "id": sli.id,
        "service_id": service.id if service else sli.service_id,
        "service_name": service.name if service else None,
        "service_slug": service.slug if service else None,
        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,
        "slug": sli.slug,
        "name": sli.name,
        "description": sli.description,
        "sli_type": sli.sli_type,
        "source": sli.source,
        "configuration": sli.configuration or {},
        "severity": sli.severity,
        "priority": sli.priority,
        "enabled": sli.enabled,
        "created_at": serialize_utc_datetime(sli.created_at),
        "updated_at": serialize_utc_datetime(sli.updated_at),
    }

    return attach_team_permissions(data, team.id if team else None, current_user)


def serialize_service_slo(slo, current_user=None, evaluation=None):
    """Serialize a Service Level Objective."""
    service = slo.service if getattr(slo, "service_id", None) else None
    team = service.team if service and getattr(service, "team_id", None) else None
    sli = slo.sli if getattr(slo, "sli_id", None) else None

    data = {
        "id": slo.id,
        "service_id": service.id if service else slo.service_id,
        "service_name": service.name if service else None,
        "service_slug": service.slug if service else None,
        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,
        "sli_id": sli.id if sli else slo.sli_id,
        "sli_name": sli.name if sli else None,
        "sli_slug": sli.slug if sli else None,
        "sli_type": sli.sli_type if sli else None,
        "name": slo.name,
        "description": slo.description,
        "comparison": slo.comparison,
        "target_percent_basis_points": slo.target_percent_basis_points,
        "threshold_seconds": slo.threshold_seconds,
        "threshold_count": slo.threshold_count,
        "window_days": slo.window_days,
        "exclude_maintenance": slo.exclude_maintenance,
        "include_open_alerts": slo.include_open_alerts,
        "enabled": slo.enabled,
        "created_at": serialize_utc_datetime(slo.created_at),
        "updated_at": serialize_utc_datetime(slo.updated_at),
    }

    if evaluation is not None:
        data["evaluation"] = evaluation

    return attach_team_permissions(data, team.id if team else None, current_user)


def _service_dependency_impact_fields(prefix, impact):
    """Serialize effective impact fields for a dependency endpoint."""

    if not impact:
        return {}

    def get(name, default=None):
        return impact.get(name, default)

    return {
        f"{prefix}_own_status": get("own_status"),
        f"{prefix}_alert_impact_status": get("alert_impact_status"),
        f"{prefix}_dependency_impact_status": get("dependency_impact_status"),
        f"{prefix}_effective_status": get("effective_status"),
        f"{prefix}_primary_reason": get("primary_reason"),
        f"{prefix}_own_impact_score": get("own_impact_score", 0),
        f"{prefix}_alert_impact_score": get("alert_impact_score", 0),
        f"{prefix}_dependency_impact_score": get("dependency_impact_score", 0),
        f"{prefix}_effective_impact_score": get("effective_impact_score", get("impact_score", 0)),
        f"{prefix}_impact_score": get("impact_score", get("effective_impact_score", 0)),
        f"{prefix}_open_alert_groups": get("open_alert_groups", 0),
        f"{prefix}_critical_open_alert_groups": get("critical_open_alert_groups", 0),
    }


def serialize_service_dependency(dependency, current_user=None, impact_by_service=None):
    """Serialize a service dependency."""
    service = dependency.service
    depends_on = dependency.depends_on_service
    impact_by_service = impact_by_service or {}

    data = {
        "id": dependency.id,

        "service_id": service.id,
        "service_name": service.name,
        "service_slug": service.slug,
        "team_id": service.team.id if service.team else None,
        "team_name": service.team.name if service.team else None,
        "team_slug": service.team.slug if service.team else None,

        "depends_on_service_id": depends_on.id,
        "depends_on_service_name": depends_on.name,
        "depends_on_service_slug": depends_on.slug,
        "depends_on_service_status": depends_on.status,

        "depends_on_team_id": depends_on.team.id if depends_on.team else None,
        "depends_on_team_name": depends_on.team.name if depends_on.team else None,
        "depends_on_team_slug": depends_on.team.slug if depends_on.team else None,

        "dependency_type": dependency.dependency_type,
        "criticality": dependency.criticality,
        "correlation_enabled": bool(getattr(dependency, "correlation_enabled", True)),
        "propagation_delay_seconds": getattr(dependency, "propagation_delay_seconds", 300),
        "description": dependency.description,
        "enabled": dependency.enabled,
        "created_at": serialize_utc_datetime(dependency.created_at),
        "updated_at": serialize_utc_datetime(dependency.updated_at),
    }

    data.update(_service_dependency_impact_fields(
        "service",
        impact_by_service.get(service.id),
    ))
    data.update(_service_dependency_impact_fields(
        "depends_on_service",
        impact_by_service.get(depends_on.id),
    ))

    return attach_team_permissions(data, service.team_id, current_user)


def serialize_maintenance_window_scope(scope):
    return {
        "id": scope.id,
        "maintenance_window_id": scope.maintenance_window_id,
        "scope_type": scope.scope_type,
        "group_id": scope.group_id,
        "team_id": scope.team_id,
        "service_id": scope.service_id,
        "route_id": scope.route_id,
        "created_at": scope.created_at.isoformat() if scope.created_at else None,
    }


def serialize_maintenance_window(window, include_scopes=True):
    data = {
        "id": window.id,
        "group_id": window.group_id,
        "group_name": window.group.name if window.group_id else None,
        "team_id": window.team_id,
        "team_name": window.team.name if window.team_id else None,
        "name": window.name,
        "description": window.description,
        "status": maintenance_repo.get_effective_window_status(window),
        "stored_status": window.status,
        "behavior": window.behavior,
        "timezone": window.timezone,
        "rrule": window.rrule,
        "starts_at": serialize_local_datetime(window.starts_at),
        "ends_at": serialize_local_datetime(window.ends_at),
        "occurrence": serialize_maintenance_window_occurrence(window),
        "enabled": window.enabled,
        "deleted": window.deleted,
        "cancelled_by_id": window.cancelled_by_id,
        "cancelled_at": window.cancelled_at.isoformat() if window.cancelled_at else None,
        "cancel_reason": window.cancel_reason,
        "created_at": window.created_at.isoformat() if getattr(window, "created_at", None) else None,
        "updated_at": window.updated_at.isoformat() if getattr(window, "updated_at", None) else None,
    }

    if include_scopes:
        data["scopes"] = [
            serialize_maintenance_window_scope(scope)
            for scope in maintenance_repo.list_maintenance_window_scopes(window)
        ]

    return data


def serialize_maintenance_window_ref(window):
    if not window:
        return None

    return {
        "id": window.id,
        "name": window.name,
        "status": maintenance_repo.get_effective_window_status(window),
        "behavior": window.behavior,
        "timezone": window.timezone,
        "starts_at": serialize_local_datetime(window.starts_at),
        "ends_at": serialize_local_datetime(window.ends_at),
        "occurrence": serialize_maintenance_window_occurrence(window),
    }


def serialize_active_maintenance_for_scope(*, group_id=None, team_id=None, service_id=None, route_id=None):
    window = maintenance_repo.find_active_maintenance_window(
        group_id=group_id,
        team_id=team_id,
        service_id=service_id,
        route_id=route_id,
    )

    return serialize_maintenance_window_ref(window)


def serialize_maintenance_window_occurrence(window):
    occurrence = maintenance_repo.get_effective_window_occurrence(window)

    if not occurrence:
        return None

    starts_at = occurrence.get("starts_at")
    ends_at = occurrence.get("ends_at")

    return {
        "status": occurrence.get("status"),
        "starts_at": starts_at.isoformat() if starts_at else None,
        "ends_at": ends_at.isoformat() if ends_at else None,
        "timezone": occurrence.get("timezone"),
        "recurring": bool(occurrence.get("recurring")),
    }
