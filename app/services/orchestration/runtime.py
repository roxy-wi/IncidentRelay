"""Runtime handoff from published orchestration definitions to alert lifecycle."""

from __future__ import annotations

import copy
import logging
import time
from datetime import timedelta
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional

from app.modules.common import utc_now
from app.settings import Config
from app.modules.db import orchestrations_repo
from app.modules.db.models import (
    AlertRoute,
    EscalationPolicy,
    EventOrchestration,
    NotificationPolicy,
    OrchestrationExecution,
    PriorityPolicy,
    Service,
    Team,
)
from app.services.orchestration.cache import published_definition_cache
from app.services.orchestration.engine import execute_rule_tree
from app.services.orchestration.fields import build_context
from app.services.orchestration.safety import safe_trace_value

logger = logging.getLogger("oncall.orchestration.runtime")

_COMPATIBILITY_ORDER = {"legacy": 0, "hybrid": 1, "orchestration": 2}


class RuntimeOrchestrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeStep:
    orchestration_id: int
    version_id: int
    scope: str
    mode: str
    compatibility_mode: str
    applied: bool
    execution_id: Optional[int]
    duration_ms: int
    matched_rule_count: int = 0
    outcome: str = "continue"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orchestration_id": self.orchestration_id,
            "version_id": self.version_id,
            "scope": self.scope,
            "mode": self.mode,
            "compatibility_mode": self.compatibility_mode,
            "applied": self.applied,
            "execution_id": self.execution_id,
            "duration_ms": self.duration_ms,
            "matched_rule_count": self.matched_rule_count,
            "outcome": self.outcome,
            "error": self.error,
        }


@dataclass
class RuntimeResult:
    group_id: Optional[int] = None
    compatibility_mode: str = "legacy"
    route: Any = None
    team: Any = None
    service: Any = None
    escalation_policy: Any = None
    priority_policy: Any = None
    notification_policy: Any = None
    group_key: Optional[str] = None
    grouping_window_seconds: Optional[int] = None
    trace_level: Optional[str] = None
    route_selected_by_orchestration: bool = False
    steps: List[RuntimeStep] = field(default_factory=list)
    blocked: bool = False
    reason: Optional[str] = None
    disposition: str = "process"
    disposition_reason: Optional[str] = None
    pause_seconds: Optional[int] = None
    pause_retrigger: str = "preserve"
    disposition_orchestration_id: Optional[int] = None
    disposition_version_id: Optional[int] = None
    evaluated_service_ids: List[int] = field(default_factory=list, repr=False)
    _context: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def execution_ids(self):
        return [step.execution_id for step in self.steps if step.execution_id]

    def to_dict(self):
        return {
            "group_id": self.group_id,
            "compatibility_mode": self.compatibility_mode,
            "route_id": getattr(self.route, "id", None),
            "team_id": getattr(self.team, "id", None),
            "service_id": getattr(self.service, "id", None),
            "escalation_policy_id": getattr(self.escalation_policy, "id", None),
            "priority_policy_id": getattr(self.priority_policy, "id", None),
            "notification_policy_id": getattr(self.notification_policy, "id", None),
            "group_key": self.group_key,
            "grouping_window_seconds": self.grouping_window_seconds,
            "trace_level": self.trace_level,
            "blocked": self.blocked,
            "reason": self.reason,
            "disposition": self.disposition,
            "disposition_reason": self.disposition_reason,
            "pause_seconds": self.pause_seconds,
            "pause_retrigger": self.pause_retrigger,
            "disposition_orchestration_id": self.disposition_orchestration_id,
            "disposition_version_id": self.disposition_version_id,
            "evaluated_service_ids": list(self.evaluated_service_ids),
            "steps": [step.to_dict() for step in self.steps],
        }



def _entity_context(entity) -> Dict[str, Any]:
    if entity is None:
        return {}
    result = {"id": getattr(entity, "id", None)}
    for key in ("name", "slug", "source", "enabled", "active"):
        value = getattr(entity, key, None)
        if value is not None:
            result[key] = value
    return result


def _route_group_id(route) -> Optional[int]:
    team = getattr(route, "team", None)
    group_id = getattr(team, "group_id", None)
    return int(group_id) if group_id is not None else None


def _group_id_from_alert(alert_data: Mapping[str, Any]) -> Optional[int]:
    explicit = alert_data.get("orchestration_group_id") or alert_data.get("group_id")
    if explicit not in (None, ""):
        try:
            return int(explicit)
        except (TypeError, ValueError):
            return None

    route_id = alert_data.get("forced_route_id")
    if route_id:
        route = AlertRoute.get_or_none(AlertRoute.id == route_id)
        return _route_group_id(route) if route else None

    team_id = alert_data.get("forced_team_id")
    if team_id:
        team = Team.get_or_none(Team.id == team_id)
        return int(team.group_id) if team and team.group_id is not None else None

    team_slug = alert_data.get("team_slug")
    if team_slug:
        team = Team.get_or_none(Team.slug == team_slug)
        return int(team.group_id) if team and team.group_id is not None else None

    return None


def _load_route(route_id: Any, *, group_id: int, source: Optional[str]):
    if route_id in (None, ""):
        return None
    route = AlertRoute.get_or_none(AlertRoute.id == int(route_id))
    if not route or not route.enabled or getattr(route, "deleted", False):
        raise RuntimeOrchestrationError("selected route is missing or disabled")
    if _route_group_id(route) != int(group_id):
        raise RuntimeOrchestrationError("selected route belongs to another group")
    if source and route.source != source:
        raise RuntimeOrchestrationError("selected route source does not match event source")
    if (
        not route.team
        or not route.team.active
        or not route.team.group
        or not route.team.group.active
    ):
        raise RuntimeOrchestrationError("selected route team or group is inactive")
    return route


def _load_team(team_id: Any, *, group_id: int):
    if team_id in (None, ""):
        return None
    team = Team.get_or_none(Team.id == int(team_id))
    if not team or not team.active or getattr(team, "deleted", False):
        raise RuntimeOrchestrationError("selected team is missing or inactive")
    if int(team.group_id or 0) != int(group_id):
        raise RuntimeOrchestrationError("selected team belongs to another group")
    return team


def _load_service(service_id: Any, *, group_id: int):
    if service_id in (None, ""):
        return None
    service = Service.get_or_none(Service.id == int(service_id))
    if not service or not service.enabled or getattr(service, "deleted", False):
        raise RuntimeOrchestrationError("selected service is missing or disabled")
    if int(service.group_id or 0) != int(group_id):
        raise RuntimeOrchestrationError("selected service belongs to another group")
    return service


def _load_policy(model, policy_id, *, group_id: int, team_id: Optional[int]):
    if policy_id in (None, ""):
        return None
    policy = model.get_or_none(model.id == int(policy_id))
    if (
        not policy
        or not getattr(policy, "enabled", False)
        or getattr(policy, "deleted", False)
    ):
        raise RuntimeOrchestrationError("selected policy is missing or disabled")
    policy_team = getattr(policy, "team", None)
    if not policy_team or int(policy_team.group_id or 0) != int(group_id):
        raise RuntimeOrchestrationError("selected policy belongs to another group")
    if team_id is not None and int(policy.team_id) != int(team_id):
        raise RuntimeOrchestrationError("selected policy belongs to another team")
    return policy


def _initial_entities(alert_data, group_id):
    route = _load_route(
        alert_data.get("forced_route_id"),
        group_id=group_id,
        source=alert_data.get("source"),
    ) if alert_data.get("forced_route_id") else None
    team = (
        route.team
        if route
        else _load_team(
            alert_data.get("forced_team_id"),
            group_id=group_id,
        )
    )
    service = (
        _load_service(alert_data.get("service_id"), group_id=group_id)
        if alert_data.get("service_id")
        else (route.service if route and getattr(route, "service_id", None) else None)
    )
    return route, team, service


def _build_runtime_context(alert_data, *, route=None, team=None, service=None):
    event = {
        str(key): copy.deepcopy(value)
        for key, value in alert_data.items()
        if key not in {"payload", "raw"} and not str(key).startswith("_orchestration")
    }
    return build_context(
        event=event,
        labels=event.get("labels") or {},
        raw=copy.deepcopy(alert_data.get("raw") or alert_data.get("payload") or {}),
        route=_entity_context(route),
        team=_entity_context(team),
        service=_entity_context(service),
        integration={
            "name": alert_data.get("source"),
            "source": alert_data.get("source"),
        },
        time={"now": utc_now().isoformat()},
    )


def _record_execution(
    *, orchestration, version, alert_data, result=None, duration_ms=0, applied=False,
    error=None, initial_context=None,
):
    trace = {
        "applied": bool(applied),
        "mode": orchestration.mode,
        "compatibility_mode": orchestration.compatibility_mode,
        "initial_context": safe_trace_value(initial_context or {}),
        "result": safe_trace_value(result.to_dict()) if result else None,
        "error": safe_trace_value(error),
    }
    disposition = None
    matched = 0
    if result is not None:
        disposition = result.context.get("result", {}).get("disposition")
        matched = result.matched_rule_count
    expires_at = None
    if disposition == "drop":
        expires_at = utc_now() + timedelta(
            days=int(getattr(Config, "ORCHESTRATION_DROPPED_TRACE_RETENTION_DAYS", 7))
        )

    row = OrchestrationExecution.create(
        group=orchestration.group_id,
        orchestration=orchestration.id,
        version=version.id,
        source=alert_data.get("source"),
        integration_name=alert_data.get("integration_name") or alert_data.get("source"),
        event_fingerprint=(
            alert_data.get("dedup_key")
            or alert_data.get("external_id")
        ),
        disposition=disposition,
        matched_rule_count=matched,
        duration_ms=duration_ms,
        trace_json=trace,
        expires_at=expires_at,
    )
    return row.id


def _safe_record_execution(**kwargs):
    try:
        return _record_execution(**kwargs)
    except Exception:
        logger.exception(
            "failed to persist orchestration execution",
            extra={"extra": {
                "orchestration_id": getattr(kwargs.get("orchestration"), "id", None),
                "version_id": getattr(kwargs.get("version"), "id", None),
            }},
        )
        return None


def _run_one(orchestration: EventOrchestration, context, alert_data):
    started = time.perf_counter()
    initial_context = copy.deepcopy(context)
    try:
        version = orchestrations_repo.get_published_runtime_version(orchestration)
        definition = published_definition_cache.get(version)
        rules = definition.get("rules") or []
        result = execute_rule_tree(rules, context)
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        applied = (
            orchestration.mode == "active"
            and orchestration.compatibility_mode != "legacy"
        )
        execution_id = _safe_record_execution(
            orchestration=orchestration,
            version=version,
            alert_data=alert_data,
            result=result,
            duration_ms=duration_ms,
            applied=applied,
            initial_context=initial_context,
        )
        return result, RuntimeStep(
            orchestration_id=orchestration.id,
            version_id=version.id,
            scope=orchestration.scope,
            mode=orchestration.mode,
            compatibility_mode=orchestration.compatibility_mode,
            applied=applied,
            execution_id=execution_id,
            duration_ms=duration_ms,
            matched_rule_count=result.matched_rule_count,
            outcome=result.outcome,
        )
    except Exception as exc:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        safe_error = exc.__class__.__name__
        version = locals().get("version")
        execution_id = None
        if version is not None:
            execution_id = _safe_record_execution(
                orchestration=orchestration,
                version=version,
                alert_data=alert_data,
                duration_ms=duration_ms,
                applied=False,
                error=safe_error,
                initial_context=initial_context,
            )
        return None, RuntimeStep(
            orchestration_id=orchestration.id,
            version_id=getattr(
                version,
                "id",
                orchestration.active_version_id or 0,
            ),
            scope=orchestration.scope,
            mode=orchestration.mode,
            compatibility_mode=orchestration.compatibility_mode,
            applied=False,
            execution_id=execution_id,
            duration_ms=duration_ms,
            error=safe_error,
            outcome="failed",
        )


def _mark_execution_rejected(step: RuntimeStep, reason: str) -> RuntimeStep:
    """Correct the audit row when a candidate fails runtime entity validation."""
    if step.execution_id:
        try:
            execution = OrchestrationExecution.get_by_id(step.execution_id)
            trace_json = copy.deepcopy(execution.trace_json or {})
            trace_json["applied"] = False
            trace_json["rejected_reason"] = safe_trace_value(reason)
            execution.trace_json = trace_json
            execution.save(only=[OrchestrationExecution.trace_json])
        except Exception:
            logger.exception(
                "failed to mark orchestration execution as rejected",
                extra={"extra": {"execution_id": step.execution_id}},
            )
    return replace(
        step,
        applied=False,
        outcome="rejected",
        error="RuntimeOrchestrationError",
    )


def _apply_candidate(candidate):
    return copy.deepcopy(candidate.context)


def _selected_ids(context):
    result = context.get("result") or {}
    routing = result.get("routing") or {}
    policies = result.get("policies") or {}
    return routing, policies, result.get("grouping") or {}


def _resolve_selected_entities(
    context, *, group_id, source, fallback_route=None, fallback_team=None,
    fallback_service=None, fallback_escalation=None, fallback_priority=None,
    fallback_notification=None,
):
    routing, policies, grouping = _selected_ids(context)
    explicit_route = routing.get("route_id") not in (None, "")
    explicit_team = routing.get("team_id") not in (None, "")
    explicit_service = routing.get("service_id") not in (None, "")

    if explicit_route:
        route = _load_route(routing.get("route_id"), group_id=group_id, source=source)
    elif explicit_team:
        route = None
    else:
        route = fallback_route

    if explicit_team:
        team = _load_team(routing.get("team_id"), group_id=group_id)
    elif route:
        team = route.team
    else:
        team = fallback_team

    if explicit_service:
        service = _load_service(routing.get("service_id"), group_id=group_id)
        if not explicit_team and not explicit_route:
            team = service.team
            if route and route.team_id != team.id:
                route = None
    elif fallback_service is not None:
        service = fallback_service
    elif route and getattr(route, "service_id", None):
        service = route.service
    else:
        service = None

    if route and team and route.team_id != team.id:
        raise RuntimeOrchestrationError("selected route and team do not match")
    if service and team and service.team_id != team.id:
        raise RuntimeOrchestrationError("selected service and team do not match")

    team_id = getattr(team, "id", None)
    escalation = (
        _load_policy(
            EscalationPolicy,
            policies.get("escalation_policy_id"),
            group_id=group_id,
            team_id=team_id,
        )
        if policies.get("escalation_policy_id") else fallback_escalation
    )
    priority = (
        _load_policy(
            PriorityPolicy,
            policies.get("priority_policy_id"),
            group_id=group_id,
            team_id=team_id,
        )
        if policies.get("priority_policy_id") else fallback_priority
    )
    notification = (
        _load_policy(
            NotificationPolicy,
            policies.get("notification_policy_id"),
            group_id=group_id,
            team_id=team_id,
        )
        if policies.get("notification_policy_id") else fallback_notification
    )
    return route, team, service, escalation, priority, notification, grouping


def _refresh_entity_context(context, *, route, team, service):
    context["route"] = _entity_context(route)
    context["team"] = _entity_context(team)
    context["service"] = _entity_context(service)


def _evaluate_orchestrations(
    orchestrations,
    *,
    context,
    alert_data,
    runtime,
    group_id,
    route,
    team,
    service,
):
    for orchestration in orchestrations:
        # Legacy mode exists only as a safe rollout default. It must not execute
        # or write shadow audit rows unless the operator explicitly switches it.
        if orchestration.mode == "active" and orchestration.compatibility_mode == "legacy":
            continue

        candidate, step = _run_one(orchestration, context, alert_data)
        if step.error:
            runtime.steps.append(step)
            if (
                orchestration.mode == "active"
                and orchestration.compatibility_mode == "orchestration"
            ):
                runtime.blocked = True
                runtime.reason = "Active orchestration evaluation failed"
                break
            continue

        if not step.applied:
            runtime.steps.append(step)
            continue

        candidate_context = _apply_candidate(candidate)
        try:
            (
                route_candidate,
                team_candidate,
                service_candidate,
                escalation,
                priority,
                notification,
                grouping,
            ) = _resolve_selected_entities(
                candidate_context,
                group_id=group_id,
                source=alert_data.get("source"),
                fallback_route=route,
                fallback_team=team,
                fallback_service=service,
                fallback_escalation=runtime.escalation_policy,
                fallback_priority=runtime.priority_policy,
                fallback_notification=runtime.notification_policy,
            )
        except RuntimeOrchestrationError as exc:
            rejected_step = _mark_execution_rejected(step, str(exc))
            runtime.steps.append(rejected_step)
            if orchestration.compatibility_mode == "orchestration":
                runtime.blocked = True
                runtime.reason = str(exc)
                break
            logger.warning(
                "hybrid orchestration result rejected",
                extra={"extra": {
                    "orchestration_id": orchestration.id,
                    "error": str(exc),
                }},
            )
            continue

        runtime.steps.append(step)
        runtime.compatibility_mode = max(
            runtime.compatibility_mode,
            orchestration.compatibility_mode,
            key=lambda value: _COMPATIBILITY_ORDER[value],
        )
        context = candidate_context
        route, team, service = route_candidate, team_candidate, service_candidate
        _refresh_entity_context(context, route=route, team=team, service=service)
        runtime.route = route
        runtime.team = team
        runtime.service = service
        runtime.escalation_policy = escalation
        runtime.priority_policy = priority
        runtime.notification_policy = notification
        routing_result = (context.get("result") or {}).get("routing") or {}

        runtime.route_selected_by_orchestration = (
                runtime.route_selected_by_orchestration
                or routing_result.get("route_id") not in (None, "")
        )

        event_group_key = (context.get("event") or {}).get("group_key")
        if grouping.get("group_key") not in (None, ""):
            runtime.group_key = grouping.get("group_key")
        elif event_group_key not in (None, ""):
            runtime.group_key = event_group_key
        if "window_seconds" in grouping:
            runtime.grouping_window_seconds = grouping.get("window_seconds")

        result_state = context.get("result") or {}
        trace_level = result_state.get("trace_level")
        if (
            orchestration.scope == "global"
            and trace_level in {"full", "compact", "disabled"}
        ):
            runtime.trace_level = trace_level

        disposition = result_state.get("disposition") or "process"
        if disposition in {"suppress", "pause", "drop"}:
            runtime.disposition = disposition
            runtime.disposition_orchestration_id = orchestration.id
            runtime.disposition_version_id = step.version_id
            if disposition == "suppress":
                runtime.disposition_reason = result_state.get("suppress_reason")
            elif disposition == "pause":
                runtime.disposition_reason = result_state.get("pause_reason")
                runtime.pause_seconds = result_state.get("pause_seconds")
                runtime.pause_retrigger = result_state.get("pause_retrigger") or "preserve"
            else:
                runtime.disposition_reason = result_state.get("drop_reason")

    runtime._context = copy.deepcopy(context)
    return context, route, team, service


_MUTABLE_EVENT_FIELDS = {
    "title",
    "message",
    "description",
    "severity",
    "priority",
    "dedup_key",
    "group_key",
    "labels",
    "custom_details",
    "event_action",
}


def _apply_runtime_to_alert_data(
    runtime: RuntimeResult,
    alert_data: Dict[str, Any],
):
    if runtime.blocked or not any(step.applied for step in runtime.steps):
        return

    event = (runtime._context or {}).get("event") or {}
    for key in _MUTABLE_EVENT_FIELDS:
        if key in event:
            alert_data[key] = copy.deepcopy(event[key])

    if event.get("event_action") == "resolve":
        alert_data["status"] = "resolved"
    elif event.get("event_action") == "trigger":
        alert_data["status"] = "firing"

    if runtime.route is not None:
        alert_data["forced_route_id"] = runtime.route.id
        alert_data["forced_team_id"] = runtime.route.team_id
    elif runtime.team is not None:
        alert_data.pop("forced_route_id", None)
        alert_data["forced_team_id"] = runtime.team.id
    if runtime.service is not None:
        alert_data["service_id"] = runtime.service.id
    if runtime.group_key:
        alert_data["orchestration_group_key"] = runtime.group_key
    if runtime.priority_policy is not None:
        alert_data["orchestration_priority_policy_id"] = runtime.priority_policy.id
    if runtime.escalation_policy is not None:
        alert_data["orchestration_escalation_policy_id"] = runtime.escalation_policy.id
    if runtime.notification_policy is not None:
        alert_data["orchestration_notification_policy_id"] = runtime.notification_policy.id
    if event.get("priority") not in (None, ""):
        alert_data["priority"] = event["priority"]
        alert_data["priority_set_by_orchestration"] = True


def _runtime_explain_payload(result: RuntimeResult) -> Dict[str, Any]:
    """Return runtime summary plus full redacted rule traces for Explain."""
    payload = result.to_dict()
    execution_ids = result.execution_ids
    if not execution_ids:
        payload["executions"] = []
        return payload

    rows = {
        row.id: row
        for row in OrchestrationExecution.select().where(
            OrchestrationExecution.id.in_(execution_ids)
        )
    }
    executions = []
    for step in result.steps:
        row = rows.get(step.execution_id)
        if row is None:
            continue
        executions.append(
            {
                "execution_id": row.id,
                "orchestration_id": row.orchestration_id,
                "version_id": row.version_id,
                "duration_ms": row.duration_ms,
                "matched_rule_count": row.matched_rule_count,
                "disposition": row.disposition,
                "trace": safe_trace_value(row.trace_json or {}),
            }
        )
    payload["executions"] = executions
    return payload


def _trace_runtime(trace, result: RuntimeResult, *, phase="global"):
    if trace is None:
        return
    status = (
        "error"
        if result.blocked
        else ("success" if result.steps else "skipped")
    )
    trace.step(
        "orchestration",
        "orchestration_runtime_blocked" if result.blocked else "orchestration_runtime_evaluated",
        status,
        (
            "Event orchestration evaluated"
            if not result.blocked
            else "Event orchestration blocked processing"
        ),
        result.reason,
        phase=phase,
        orchestration=_runtime_explain_payload(result),
    )


def _evaluate_service_chain(
    alert_data,
    runtime,
    *,
    context,
    route,
    team,
    service,
):
    """Run each selected service orchestration once, including service handoffs."""
    current_service = service
    iterations = 0
    while current_service is not None and not runtime.blocked:
        service_id = int(current_service.id)
        if service_id in runtime.evaluated_service_ids:
            break
        if iterations >= 8:
            runtime.blocked = runtime.compatibility_mode == "orchestration"
            runtime.reason = "Service orchestration handoff limit exceeded"
            break
        iterations += 1
        runtime.evaluated_service_ids.append(service_id)
        orchestrations = orchestrations_repo.list_runtime_orchestrations(
            group_id=runtime.group_id,
            scope="service",
            service_id=service_id,
        )
        context, route, team, selected_service = _evaluate_orchestrations(
            orchestrations,
            context=context,
            alert_data=alert_data,
            runtime=runtime,
            group_id=runtime.group_id,
            route=route,
            team=team,
            service=current_service,
        )
        current_service = selected_service
    return context, route, team, current_service


def run_event_orchestration(alert_data: Dict[str, Any], *, trace=None) -> RuntimeResult:
    """Evaluate published global orchestration before legacy lifecycle routing."""
    runtime = RuntimeResult()
    group_id = _group_id_from_alert(alert_data)
    runtime.group_id = group_id
    if group_id is None:
        _trace_runtime(trace, runtime)
        return runtime

    global_orchestrations = orchestrations_repo.list_runtime_orchestrations(
        group_id=group_id,
        scope="global",
    )
    try:
        route, team, service = _initial_entities(alert_data, group_id)
    except RuntimeOrchestrationError as exc:
        requires_orchestration = any(
            item.mode == "active" and item.compatibility_mode == "orchestration"
            for item in global_orchestrations
        )
        if requires_orchestration:
            runtime.blocked = True
            runtime.reason = str(exc)
        _trace_runtime(trace, runtime)
        return runtime

    runtime.route = route
    runtime.team = team
    runtime.service = service
    if not global_orchestrations and service is None:
        _trace_runtime(trace, runtime)
        return runtime

    context = _build_runtime_context(alert_data, route=route, team=team, service=service)
    context, route, team, service = _evaluate_orchestrations(
        global_orchestrations,
        context=context,
        alert_data=alert_data,
        runtime=runtime,
        group_id=group_id,
        route=route,
        team=team,
        service=service,
    )

    if not runtime.blocked and service is not None:
        context, route, team, service = _evaluate_service_chain(
            alert_data,
            runtime,
            context=context,
            route=route,
            team=team,
            service=service,
        )

    runtime._context = copy.deepcopy(context)
    runtime.route = route
    runtime.team = team
    runtime.service = service

    if (
        not runtime.blocked
        and runtime.compatibility_mode == "orchestration"
        and runtime.route is None
    ):
        runtime.blocked = True
        runtime.reason = "Orchestration mode requires a selected route"

    _apply_runtime_to_alert_data(runtime, alert_data)
    _trace_runtime(trace, runtime)
    return runtime


def run_service_orchestration(
    alert_data: Dict[str, Any],
    runtime: Optional[RuntimeResult],
    *,
    route,
    team,
    service,
    trace=None,
) -> RuntimeResult:
    """Run service-scoped orchestration after the lifecycle selects a service."""
    runtime = runtime or RuntimeResult(group_id=_route_group_id(route))
    if runtime.blocked or service is None or runtime.group_id is None:
        return runtime

    previous_step_count = len(runtime.steps)
    context = (
        copy.deepcopy(runtime._context)
        if runtime._context
        else _build_runtime_context(
            alert_data,
            route=route,
            team=team,
            service=service,
        )
    )
    _refresh_entity_context(context, route=route, team=team, service=service)
    runtime.route = route
    runtime.team = team
    runtime.service = service

    context, route, team, service = _evaluate_service_chain(
        alert_data,
        runtime,
        context=context,
        route=route,
        team=team,
        service=service,
    )
    runtime._context = copy.deepcopy(context)
    runtime.route = route
    runtime.team = team
    runtime.service = service

    if (
        not runtime.blocked
        and runtime.compatibility_mode == "orchestration"
        and runtime.route is None
    ):
        runtime.blocked = True
        runtime.reason = "Orchestration mode requires a selected route"

    _apply_runtime_to_alert_data(runtime, alert_data)
    if runtime.blocked or len(runtime.steps) != previous_step_count:
        _trace_runtime(trace, runtime, phase="service")
    return runtime


def _actual_result_snapshot(*, group=None, alert=None) -> Dict[str, Any]:
    """Capture the lifecycle result used to compare a shadow candidate."""
    route_id = getattr(alert, "route_id", None) or getattr(group, "route_id", None)
    team_id = getattr(alert, "team_id", None) or getattr(group, "team_id", None)
    service_id = getattr(alert, "service_id", None) or getattr(group, "service_id", None)
    suppressed = bool(
        getattr(alert, "orchestration_suppressed", False)
        or getattr(group, "orchestration_suppressed", False)
    )
    return {
        "route_id": route_id,
        "team_id": team_id,
        "service_id": service_id,
        "severity": getattr(alert, "severity", None),
        "title": getattr(alert, "title", None),
        "group_key": (
            getattr(alert, "group_key", None)
            or getattr(group, "group_key", None)
        ),
        "status": getattr(alert, "status", None) or getattr(group, "status", None),
        "disposition": "suppress" if suppressed else "process",
        "alert_id": getattr(alert, "id", None),
        "alert_group_id": getattr(group, "id", None),
    }


def attach_runtime_executions(
    runtime: Optional[RuntimeResult],
    *,
    group=None,
    alert=None,
):
    if runtime is None or not runtime.execution_ids:
        return
    execution_ids = list(runtime.execution_ids)
    OrchestrationExecution.update(
        alert_group_id=getattr(group, "id", None),
        alert_id=getattr(alert, "id", None),
    ).where(OrchestrationExecution.id.in_(execution_ids)).execute()

    actual_result = safe_trace_value(
        _actual_result_snapshot(group=group, alert=alert)
    )
    for execution in OrchestrationExecution.select().where(
        OrchestrationExecution.id.in_(execution_ids)
    ):
        trace_json = copy.deepcopy(execution.trace_json or {})
        trace_json["actual_result"] = actual_result
        execution.trace_json = trace_json
        execution.save(only=[OrchestrationExecution.trace_json])

    # Queue outbound automation only after the orchestration decision and the
    # lifecycle outcome have been persisted. The queue function is idempotent.
    from app.services.orchestration.webhooks import enqueue_execution_webhooks

    for execution_id in execution_ids:
        try:
            enqueue_execution_webhooks(
                execution_id,
                alert_group_id=getattr(group, "id", None),
            )
        except Exception:
            logger.exception(
                "failed to enqueue orchestration webhook actions",
                extra={"extra": {"execution_id": execution_id}},
            )




def restore_runtime_result(data: Mapping[str, Any]) -> RuntimeResult:
    """Restore trusted runtime metadata stored with a paused event."""
    payload = dict(data or {})
    steps = []
    for item in payload.get("steps") or []:
        try:
            steps.append(RuntimeStep(**item))
        except (TypeError, ValueError):
            continue

    runtime = RuntimeResult(
        group_id=payload.get("group_id"),
        compatibility_mode=payload.get("compatibility_mode") or "legacy",
        route=AlertRoute.get_or_none(AlertRoute.id == payload.get("route_id"))
        if payload.get("route_id") else None,
        team=Team.get_or_none(Team.id == payload.get("team_id"))
        if payload.get("team_id") else None,
        service=Service.get_or_none(Service.id == payload.get("service_id"))
        if payload.get("service_id") else None,
        escalation_policy=EscalationPolicy.get_or_none(
            EscalationPolicy.id == payload.get("escalation_policy_id")
        ) if payload.get("escalation_policy_id") else None,
        priority_policy=PriorityPolicy.get_or_none(
            PriorityPolicy.id == payload.get("priority_policy_id")
        ) if payload.get("priority_policy_id") else None,
        notification_policy=NotificationPolicy.get_or_none(
            NotificationPolicy.id == payload.get("notification_policy_id")
        ) if payload.get("notification_policy_id") else None,
        group_key=payload.get("group_key"),
        grouping_window_seconds=payload.get("grouping_window_seconds"),
        trace_level=payload.get("trace_level"),
        route_selected_by_orchestration=bool(
            payload.get("route_selected_by_orchestration")
        ),
        steps=steps,
        blocked=bool(payload.get("blocked")),
        reason=payload.get("reason"),
        disposition=payload.get("disposition") or "process",
        disposition_reason=payload.get("disposition_reason"),
        pause_seconds=payload.get("pause_seconds"),
        pause_retrigger=payload.get("pause_retrigger") or "preserve",
        disposition_orchestration_id=payload.get("disposition_orchestration_id"),
        disposition_version_id=payload.get("disposition_version_id"),
        evaluated_service_ids=[
            int(value) for value in payload.get("evaluated_service_ids") or []
        ],
    )
    if runtime.team is None and runtime.route is not None:
        runtime.team = runtime.route.team
    return runtime

__all__ = [
    "RuntimeOrchestrationError",
    "RuntimeResult",
    "RuntimeStep",
    "attach_runtime_executions",
    "run_event_orchestration",
    "run_service_orchestration",
    "restore_runtime_result",
]
