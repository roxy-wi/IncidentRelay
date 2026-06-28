import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.db.models import (
    AlertRoute,
    EscalationPolicy,
    EscalationPolicyRule,
    NotificationChannel,
    NotificationPolicy,
    NotificationPolicyRule,
    NotificationPolicyRuleChannel,
    Rotation,
    Service,
    ServiceChannel,
    ServiceDependency,
    ServiceLink,
    ServiceMatchRule,
    ServiceOwner,
    ServiceReadinessCheckResult,
    ServiceReadinessEvaluation,
    ServiceReadinessState,
    ServiceRunbook,
    ServiceStandardCheck,
)
from app.services.service_catalog.standards import list_applicable_standards
from app.services.service_catalog.timeline import publish_service_event


logger = logging.getLogger("oncall.services.readiness")


@dataclass(frozen=True)
class CheckOutcome:
    status: str
    message: str
    details: dict


def evaluate_service_readiness(service, *, trigger="system", actor_user=None):
    batch_uid = uuid.uuid4()
    evaluated_at = datetime.utcnow()
    standards = list_applicable_standards(service)
    database = Service._meta.database

    with database.atomic():
        evaluation_records = [
            _evaluate_standard(
                service,
                standard,
                batch_uid=batch_uid,
                trigger=trigger,
                actor_user=actor_user,
                evaluated_at=evaluated_at,
            )
            for standard in standards
        ]

        state = _save_readiness_state(
            service,
            evaluation_records,
            batch_uid=batch_uid,
            actor_user=actor_user,
            evaluated_at=evaluated_at,
        )

    return {
        "state": state,
        "evaluations": [record["evaluation"] for record in evaluation_records],
    }


def get_service_readiness_state(service_id):
    return ServiceReadinessState.get_or_none(
        ServiceReadinessState.service == service_id
    )


def list_service_readiness_states(service_ids):
    if not service_ids:
        return {}

    states = ServiceReadinessState.select().where(
        ServiceReadinessState.service.in_(service_ids)
    )

    return {state.service_id: state for state in states}


def load_service_readiness_batch(service_id):
    state = get_service_readiness_state(service_id)

    if state is None:
        return None, [], {}

    evaluations = list(
        ServiceReadinessEvaluation.select()
        .where(
            ServiceReadinessEvaluation.service == service_id,
            ServiceReadinessEvaluation.batch_uid == state.batch_uid,
        )
        .order_by(ServiceReadinessEvaluation.id)
    )

    if not evaluations:
        return state, [], {}

    evaluation_ids = [evaluation.id for evaluation in evaluations]
    results_by_evaluation = {evaluation_id: [] for evaluation_id in evaluation_ids}

    results = (
        ServiceReadinessCheckResult.select()
        .where(ServiceReadinessCheckResult.evaluation.in_(evaluation_ids))
        .order_by(
            ServiceReadinessCheckResult.evaluation,
            ServiceReadinessCheckResult.id,
        )
    )

    for result in results:
        results_by_evaluation[result.evaluation_id].append(result)

    return state, evaluations, results_by_evaluation


def evaluate_check(service, check):
    handler = CHECK_HANDLERS.get(check.check_type)

    if handler is None:
        return CheckOutcome(
            status="error",
            message=f'Unsupported readiness check type "{check.check_type}"',
            details={"check_type": check.check_type},
        )

    try:
        return handler(service, check.configuration or {})
    except Exception as exc:
        logger.exception(
            "service readiness check failed",
            extra={
                "service_id": service.id,
                "check_id": check.id,
                "check_type": check.check_type,
            },
        )

        return CheckOutcome(
            status="error",
            message="Readiness check could not be evaluated",
            details={
                "check_type": check.check_type,
                "error_type": exc.__class__.__name__,
            },
        )


def _evaluate_standard(
    service,
    standard,
    *,
    batch_uid,
    trigger,
    actor_user,
    evaluated_at,
):
    checks = list(
        ServiceStandardCheck.select()
        .where(
            ServiceStandardCheck.standard == standard.id,
            ServiceStandardCheck.enabled == True,
            ServiceStandardCheck.deleted == False,
        )
        .order_by(ServiceStandardCheck.position, ServiceStandardCheck.id)
    )

    result_snapshots = []

    for check in checks:
        outcome = evaluate_check(service, check)
        weight = max(1, int(check.weight or 1))

        result_snapshots.append(
            {
                "check": check,
                "check_uid": check.uid,
                "check_slug": check.slug,
                "check_name": check.name,
                "check_type": check.check_type,
                "status": outcome.status,
                "weight": weight,
                "severity": check.severity,
                "required": check.required,
                "message": outcome.message,
                "details": outcome.details,
            }
        )

    passed_weight = sum(
        result["weight"]
        for result in result_snapshots
        if result["status"] == "passed"
    )
    total_weight = sum(result["weight"] for result in result_snapshots)
    score = round(passed_weight * 100 / total_weight) if total_weight else 0
    failed_results = [
        result for result in result_snapshots if result["status"] != "passed"
    ]
    failed_required = [
        result for result in failed_results if result["required"]
    ]
    failed_critical = [
        result
        for result in failed_results
        if result["severity"] == "critical" or result["status"] == "error"
    ]

    status = _calculate_standard_status(
        score,
        result_snapshots,
        failed_required,
        failed_critical,
    )

    content_hash = _hash_payload(
        {
            "standard_uid": str(standard.uid),
            "status": status,
            "score": score,
            "passed_weight": passed_weight,
            "total_weight": total_weight,
            "results": [
                {
                    "check_uid": str(result["check_uid"]),
                    "status": result["status"],
                    "weight": result["weight"],
                    "severity": result["severity"],
                    "required": result["required"],
                    "message": result["message"],
                    "details": result["details"],
                }
                for result in result_snapshots
            ],
        }
    )

    evaluation = ServiceReadinessEvaluation.create(
        batch_uid=batch_uid,
        service=service,
        standard=standard,
        status=status,
        score=score,
        passed_weight=passed_weight,
        total_weight=total_weight,
        checks_count=len(result_snapshots),
        failed_count=len(failed_results),
        failed_required_count=len(failed_required),
        failed_critical_count=len(failed_critical),
        trigger=trigger,
        actor_user=actor_user,
        content_hash=content_hash,
        evaluated_at=evaluated_at,
    )

    result_models = []

    for result in result_snapshots:
        result_models.append(
            ServiceReadinessCheckResult.create(
                evaluation=evaluation,
                check=result["check"],
                check_uid=result["check_uid"],
                check_slug=result["check_slug"],
                check_name=result["check_name"],
                check_type=result["check_type"],
                status=result["status"],
                weight=result["weight"],
                severity=result["severity"],
                required=result["required"],
                message=result["message"],
                details=result["details"],
                evaluated_at=evaluated_at,
            )
        )

    return {
        "evaluation": evaluation,
        "results": result_models,
    }


def _calculate_standard_status(
    score,
    results,
    failed_required,
    failed_critical,
):
    if not results:
        return "not_applicable"

    if failed_critical:
        return "not_ready"

    if score < 70:
        return "not_ready"

    if failed_required or score < 90:
        return "warning"

    return "ready"


def _save_readiness_state(
    service,
    evaluation_records,
    *,
    batch_uid,
    actor_user,
    evaluated_at,
):
    evaluations = [
        record["evaluation"] for record in evaluation_records
    ]
    previous_state = ServiceReadinessState.get_or_none(
        ServiceReadinessState.service == service.id
    )
    previous_snapshot = _state_snapshot(previous_state)

    passed_weight = sum(
        evaluation.passed_weight for evaluation in evaluations
    )
    total_weight = sum(
        evaluation.total_weight for evaluation in evaluations
    )
    score = round(passed_weight * 100 / total_weight) if total_weight else 0
    statuses = [
        evaluation.status
        for evaluation in evaluations
        if evaluation.status != "not_applicable"
    ]

    if not statuses:
        status = "not_applicable"
    elif "not_ready" in statuses:
        status = "not_ready"
    elif "warning" in statuses:
        status = "warning"
    else:
        status = "ready"

    values = {
        "batch_uid": batch_uid,
        "status": status,
        "score": score,
        "standards_count": len(evaluations),
        "checks_count": sum(
            evaluation.checks_count for evaluation in evaluations
        ),
        "failed_count": sum(
            evaluation.failed_count for evaluation in evaluations
        ),
        "failed_required_count": sum(
            evaluation.failed_required_count
            for evaluation in evaluations
        ),
        "failed_critical_count": sum(
            evaluation.failed_critical_count
            for evaluation in evaluations
        ),
        "evaluated_at": evaluated_at,
    }

    values["content_hash"] = _hash_payload(
        {
            "status": values["status"],
            "score": values["score"],
            "standards_count": values["standards_count"],
            "checks_count": values["checks_count"],
            "failed_count": values["failed_count"],
            "failed_required_count": values["failed_required_count"],
            "failed_critical_count": values["failed_critical_count"],
            "evaluations": [
                {
                    "standard_id": evaluation.standard_id,
                    "content_hash": evaluation.content_hash,
                }
                for evaluation in evaluations
            ],
        }
    )

    if previous_state is None:
        state = ServiceReadinessState.create(service=service, **values)
    else:
        for field, value in values.items():
            setattr(previous_state, field, value)

        previous_state.save()
        state = previous_state

    if previous_snapshot is None or previous_snapshot["content_hash"] != state.content_hash:
        _publish_readiness_event(
            service,
            state,
            evaluation_records,
            previous_snapshot=previous_snapshot,
            actor_user=actor_user,
        )

    return state


def _publish_readiness_event(
    service,
    state,
    evaluation_records,
    *,
    previous_snapshot,
    actor_user,
):
    failed_checks = []

    for record in evaluation_records:
        evaluation = record["evaluation"]

        for result in record["results"]:
            if result.status == "passed":
                continue

            failed_checks.append(
                {
                    "standard_id": evaluation.standard_id,
                    "check_uid": str(result.check_uid),
                    "check_slug": result.check_slug,
                    "check_name": result.check_name,
                    "status": result.status,
                    "severity": result.severity,
                    "required": result.required,
                    "message": result.message,
                    "details": result.details,
                }
            )

    if previous_snapshot is None:
        event_type = "readiness.evaluated"
        title = f"Service readiness evaluated: {state.score}/100"
    else:
        event_type = "readiness.score_changed"
        title = (
            f"Service readiness changed from "
            f'{previous_snapshot["score"]}/100 to {state.score}/100'
        )

    publish_service_event(
        service,
        category="readiness",
        event_type=event_type,
        title=title,
        source="readiness",
        actor_user=actor_user,
        status=state.status,
        payload={
            "previous": previous_snapshot,
            "current": _state_snapshot(state),
            "failed_checks": failed_checks,
        },
    )


def _state_snapshot(state):
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
        "content_hash": state.content_hash,
    }


def _hash_payload(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def _passed(message, **details):
    return CheckOutcome(
        status="passed",
        message=message,
        details=details,
    )


def _failed(message, **details):
    return CheckOutcome(
        status="failed",
        message=message,
        details=details,
    )


def _check_field_present(service, configuration):
    field = configuration.get("field")

    if not field:
        return CheckOutcome(
            status="error",
            message='Check configuration requires "field"',
            details={},
        )

    if not hasattr(service, field):
        return CheckOutcome(
            status="error",
            message=f'Service field "{field}" does not exist',
            details={"field": field},
        )

    value = getattr(service, field)
    present = value is not None and value != "" and value != [] and value != {}

    if present:
        return _passed(
            f'Service field "{field}" is configured',
            field=field,
            value=_safe_value(value),
        )

    return _failed(
        f'Service field "{field}" is not configured',
        field=field,
    )


def _check_field_equals(service, configuration):
    field = configuration.get("field")

    if not field or "value" not in configuration:
        return CheckOutcome(
            status="error",
            message='Check configuration requires "field" and "value"',
            details={},
        )

    if not hasattr(service, field):
        return CheckOutcome(
            status="error",
            message=f'Service field "{field}" does not exist',
            details={"field": field},
        )

    actual = _safe_value(getattr(service, field))
    expected = configuration["value"]

    if actual == expected:
        return _passed(
            f'Service field "{field}" has the expected value',
            field=field,
            actual=actual,
            expected=expected,
        )

    return _failed(
        f'Service field "{field}" does not have the expected value',
        field=field,
        actual=actual,
        expected=expected,
    )


def _check_owner_exists(service, configuration):
    roles = configuration.get("roles") or []
    minimum = max(1, int(configuration.get("minimum", 1)))

    query = ServiceOwner.select().where(
        ServiceOwner.service == service.id,
        ServiceOwner.active == True,
    )

    if roles:
        query = query.where(ServiceOwner.role.in_(roles))

    count = query.count()

    if count >= minimum:
        return _passed(
            f"Service has {count} active owner(s)",
            count=count,
            minimum=minimum,
            roles=roles,
        )

    return _failed(
        f"Service requires at least {minimum} active owner(s)",
        count=count,
        minimum=minimum,
        roles=roles,
    )


def _check_active_rotation_exists(service, configuration):
    if service.default_rotation_id is None:
        return _failed("Service has no default rotation")

    rotation = Rotation.get_or_none(
        Rotation.id == service.default_rotation_id,
        Rotation.enabled == True,
        Rotation.deleted == False,
    )

    if rotation:
        return _passed(
            "Service has an active default rotation",
            rotation_id=rotation.id,
            rotation_name=rotation.name,
        )

    return _failed(
        "Service default rotation is disabled or deleted",
        rotation_id=service.default_rotation_id,
    )


def _check_escalation_policy_exists(service, configuration):
    if service.default_escalation_policy_id is None:
        return _failed("Service has no default escalation policy")

    policy = EscalationPolicy.get_or_none(
        EscalationPolicy.id == service.default_escalation_policy_id,
        EscalationPolicy.enabled == True,
        EscalationPolicy.deleted == False,
    )

    if policy is None:
        return _failed(
            "Service escalation policy is disabled or deleted",
            policy_id=service.default_escalation_policy_id,
        )

    require_rules = configuration.get("require_rules", True)

    if require_rules:
        rules_count = (
            EscalationPolicyRule.select()
            .where(
                EscalationPolicyRule.policy == policy.id,
                EscalationPolicyRule.enabled == True,
            )
            .count()
        )

        if rules_count == 0:
            return _failed(
                "Service escalation policy has no active rules",
                policy_id=policy.id,
            )
    else:
        rules_count = None

    return _passed(
        "Service has an active escalation policy",
        policy_id=policy.id,
        policy_name=policy.name,
        rules_count=rules_count,
    )


def _check_notification_policy_exists(service, configuration):
    if service.notification_policy_id is None:
        return _failed("Service has no notification policy")

    policy = NotificationPolicy.get_or_none(
        NotificationPolicy.id == service.notification_policy_id,
        NotificationPolicy.enabled == True,
        NotificationPolicy.deleted == False,
    )

    if policy is None:
        return _failed(
            "Service notification policy is disabled or deleted",
            policy_id=service.notification_policy_id,
        )

    require_rules = configuration.get("require_rules", True)
    require_channels = configuration.get("require_channels", True)

    rules = list(
        NotificationPolicyRule.select()
        .where(
            NotificationPolicyRule.policy == policy.id,
            NotificationPolicyRule.enabled == True,
            NotificationPolicyRule.deleted == False,
        )
        .order_by(
            NotificationPolicyRule.position,
            NotificationPolicyRule.id,
        )
    )

    if require_rules and not rules:
        return _failed(
            "Service notification policy has no active rules",
            policy_id=policy.id,
        )

    if require_channels and rules:
        rule_ids = [rule.id for rule in rules]
        channel_count = (
            NotificationPolicyRuleChannel.select()
            .join(NotificationChannel)
            .where(
                NotificationPolicyRuleChannel.rule.in_(rule_ids),
                NotificationChannel.enabled == True,
                NotificationChannel.deleted == False,
            )
            .count()
        )

        if channel_count == 0:
            return _failed(
                "Service notification policy has no active channels",
                policy_id=policy.id,
                rules_count=len(rules),
            )
    else:
        channel_count = None

    return _passed(
        "Service has an active notification policy",
        policy_id=policy.id,
        policy_name=policy.name,
        rules_count=len(rules),
        channel_count=channel_count,
    )


def _check_service_channel_exists(service, configuration):
    purposes = configuration.get("purposes") or []
    minimum = max(1, int(configuration.get("minimum", 1)))

    query = (
        ServiceChannel.select()
        .join(NotificationChannel)
        .where(
            ServiceChannel.service == service.id,
            ServiceChannel.enabled == True,
            NotificationChannel.enabled == True,
            NotificationChannel.deleted == False,
        )
    )

    if purposes:
        query = query.where(ServiceChannel.purpose.in_(purposes))

    count = query.count()

    if count >= minimum:
        return _passed(
            f"Service has {count} active channel(s)",
            count=count,
            minimum=minimum,
            purposes=purposes,
        )

    return _failed(
        f"Service requires at least {minimum} active channel(s)",
        count=count,
        minimum=minimum,
        purposes=purposes,
    )


def _check_route_exists(service, configuration):
    direct_route = AlertRoute.get_or_none(
        AlertRoute.service == service.id,
        AlertRoute.enabled == True,
        AlertRoute.deleted == False,
    )

    if direct_route:
        return _passed(
            "Service has an active direct alert route",
            route_id=direct_route.id,
            route_name=direct_route.name,
            source="direct",
        )

    rules = ServiceMatchRule.select().where(
        ServiceMatchRule.service == service.id,
        ServiceMatchRule.route.is_null(False),
        ServiceMatchRule.enabled == True,
        ServiceMatchRule.deleted == False,
    )

    for rule in rules:
        route = rule.route

        if route and route.enabled and not route.deleted:
            return _passed(
                "Service has an active route through a match rule",
                route_id=route.id,
                route_name=route.name,
                match_rule_id=rule.id,
                source="match_rule",
            )

    return _failed("Service has no active alert route")


def _check_match_rule_exists(service, configuration):
    minimum = max(1, int(configuration.get("minimum", 1)))
    count = (
        ServiceMatchRule.select()
        .where(
            ServiceMatchRule.service == service.id,
            ServiceMatchRule.enabled == True,
            ServiceMatchRule.deleted == False,
        )
        .count()
    )

    if count >= minimum:
        return _passed(
            f"Service has {count} active match rule(s)",
            count=count,
            minimum=minimum,
        )

    return _failed(
        f"Service requires at least {minimum} active match rule(s)",
        count=count,
        minimum=minimum,
    )


def _check_runbook_exists(service, configuration):
    minimum = max(1, int(configuration.get("minimum", 1)))
    severities = configuration.get("severities") or []

    query = ServiceRunbook.select().where(
        ServiceRunbook.service == service.id,
        ServiceRunbook.enabled == True,
        ServiceRunbook.deleted == False,
    )

    if severities:
        query = query.where(ServiceRunbook.severity.in_(severities))

    count = query.count()

    if count >= minimum:
        return _passed(
            f"Service has {count} active runbook(s)",
            count=count,
            minimum=minimum,
            severities=severities,
        )

    return _failed(
        f"Service requires at least {minimum} active runbook(s)",
        count=count,
        minimum=minimum,
        severities=severities,
    )


def _check_link_type_exists(service, configuration):
    link_types = configuration.get("link_types") or []

    if not link_types and configuration.get("link_type"):
        link_types = [configuration["link_type"]]

    minimum = max(1, int(configuration.get("minimum", 1)))

    query = ServiceLink.select().where(
        ServiceLink.service == service.id,
        ServiceLink.enabled == True,
        ServiceLink.deleted == False,
    )

    if link_types:
        query = query.where(ServiceLink.link_type.in_(link_types))

    count = query.count()

    if count >= minimum:
        return _passed(
            f"Service has {count} matching link(s)",
            count=count,
            minimum=minimum,
            link_types=link_types,
        )

    return _failed(
        f"Service requires at least {minimum} matching link(s)",
        count=count,
        minimum=minimum,
        link_types=link_types,
    )


def _check_dependency_exists(service, configuration):
    minimum = max(1, int(configuration.get("minimum", 1)))
    dependency_types = configuration.get("dependency_types") or []
    criticalities = configuration.get("criticalities") or []

    query = ServiceDependency.select().where(
        ServiceDependency.service == service.id,
        ServiceDependency.enabled == True,
        ServiceDependency.deleted == False,
    )

    if dependency_types:
        query = query.where(
            ServiceDependency.dependency_type.in_(dependency_types)
        )

    if criticalities:
        query = query.where(
            ServiceDependency.criticality.in_(criticalities)
        )

    if configuration.get("correlation_enabled") is not None:
        query = query.where(
            ServiceDependency.correlation_enabled
            == bool(configuration["correlation_enabled"])
        )

    count = query.count()

    if count >= minimum:
        return _passed(
            f"Service has {count} matching dependency relation(s)",
            count=count,
            minimum=minimum,
            dependency_types=dependency_types,
            criticalities=criticalities,
        )

    return _failed(
        f"Service requires at least {minimum} matching dependency relation(s)",
        count=count,
        minimum=minimum,
        dependency_types=dependency_types,
        criticalities=criticalities,
    )


def _check_dependency_cycle_absent(service, configuration):
    query = ServiceDependency.select().where(
        ServiceDependency.enabled == True,
        ServiceDependency.deleted == False,
    )

    if configuration.get("correlation_only"):
        query = query.where(
            ServiceDependency.correlation_enabled == True
        )

    graph = {}

    for dependency in query:
        graph.setdefault(dependency.service_id, []).append(
            dependency.depends_on_service_id
        )

    cycle = _find_cycle_from_service(service.id, graph)

    if cycle is None:
        return _passed("Service is not part of a dependency cycle")

    names = {
        row.id: row.name
        for row in Service.select(Service.id, Service.name).where(
            Service.id.in_(set(cycle))
        )
    }

    return _failed(
        "Service is part of a dependency cycle",
        cycle_service_ids=cycle,
        cycle_service_names=[names.get(service_id) for service_id in cycle],
    )


def _check_metadata_value(service, configuration):
    key = configuration.get("key")

    if not key:
        return CheckOutcome(
            status="error",
            message='Check configuration requires "key"',
            details={},
        )

    found, actual = _read_mapping_path(service.metadata or {}, key)

    if "value" not in configuration:
        if found:
            return _passed(
                f'Service metadata key "{key}" exists',
                key=key,
                actual=_safe_value(actual),
            )

        return _failed(
            f'Service metadata key "{key}" does not exist',
            key=key,
        )

    expected = configuration["value"]

    if found and actual == expected:
        return _passed(
            f'Service metadata key "{key}" has the expected value',
            key=key,
            actual=_safe_value(actual),
            expected=expected,
        )

    return _failed(
        f'Service metadata key "{key}" does not have the expected value',
        key=key,
        actual=_safe_value(actual) if found else None,
        expected=expected,
    )


def _find_cycle_from_service(start_service_id, graph):
    def visit(current_service_id, path):
        for dependency_id in graph.get(current_service_id, []):
            if dependency_id == start_service_id:
                return path + [dependency_id]

            if dependency_id in path:
                continue

            cycle = visit(
                dependency_id,
                path + [dependency_id],
            )

            if cycle:
                return cycle

        return None

    return visit(start_service_id, [start_service_id])


def _read_mapping_path(mapping, path):
    current = mapping

    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None

        current = current[part]

    return True, current


def _safe_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [_safe_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
        }

    if hasattr(value, "id"):
        return value.id

    return str(value)


CHECK_HANDLERS = {
    "field_present": _check_field_present,
    "field_equals": _check_field_equals,
    "owner_exists": _check_owner_exists,
    "active_rotation_exists": _check_active_rotation_exists,
    "escalation_policy_exists": _check_escalation_policy_exists,
    "notification_policy_exists": _check_notification_policy_exists,
    "service_channel_exists": _check_service_channel_exists,
    "route_exists": _check_route_exists,
    "match_rule_exists": _check_match_rule_exists,
    "runbook_exists": _check_runbook_exists,
    "link_type_exists": _check_link_type_exists,
    "dependency_exists": _check_dependency_exists,
    "dependency_cycle_absent": _check_dependency_cycle_absent,
    "metadata_value": _check_metadata_value,
}
