"""Safe Event Orchestration simulation, replay and shadow analytics.

The simulator evaluates isolated event copies. It never calls the alert
lifecycle, persists orchestration executions, creates pending events, or
queues webhook actions.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.modules.common import parse_datetime, utc_now
from app.modules.db import orchestrations_repo
from app.modules.db.models import (
    Alert,
    EventOrchestration,
    EventOrchestrationVersion,
    OrchestrationExecution,
)
from app.services.integrations.normalizers.registry import (
    SUPPORTED_NORMALIZER_SOURCES,
    UnknownNormalizerSource,
    normalize_for_source,
)
from app.services.orchestration.actions import EventActionState
from app.services.orchestration.engine import execute_rule_tree
from app.services.orchestration.runtime import (
    RuntimeOrchestrationError,
    _build_runtime_context,
    _initial_entities,
    _resolve_selected_entities,
)
from app.services.orchestration.safety import (
    OrchestrationJsonError,
    ensure_json_size,
    safe_trace_value,
)
from app.settings import Config


SUPPORTED_SIMULATION_SOURCES = SUPPORTED_NORMALIZER_SOURCES


class OrchestrationSimulationError(ValueError):
    """Base error for invalid or inaccessible simulation inputs."""


class OrchestrationSimulationNotFound(OrchestrationSimulationError):
    pass


class OrchestrationSimulationConflict(OrchestrationSimulationError):
    pass


@dataclass(frozen=True)
class ReplayInput:
    kind: str
    id: int
    event: Dict[str, Any]




def _iso_datetime(value: Any) -> Optional[str]:
    parsed = parse_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _ensure_payload_size(value: Any, *, label: str) -> None:
    maximum = max(
        1024,
        int(
            getattr(
                Config,
                "ORCHESTRATION_SIMULATION_MAX_PAYLOAD_BYTES",
                1048576,
            )
        ),
    )
    try:
        ensure_json_size(value, maximum_bytes=maximum, label=label)
    except OrchestrationJsonError as exc:
        message = str(exc)
        if " exceeds the " in message:
            message = f"{label} exceeds the {maximum}-byte simulation limit"
        raise OrchestrationSimulationError(message) from exc


def get_orchestration(orchestration_id: int) -> EventOrchestration:
    row = EventOrchestration.get_or_none(
        (EventOrchestration.id == orchestration_id)
        & (EventOrchestration.deleted == False)  # noqa: E712
        & EventOrchestration.deleted_at.is_null(True)
    )
    if row is None:
        raise OrchestrationSimulationNotFound("Orchestration not found")
    return row


def get_simulation_version(
    orchestration: EventOrchestration,
    version_id: Optional[int] = None,
) -> EventOrchestrationVersion:
    if version_id is not None:
        version = EventOrchestrationVersion.get_or_none(
            EventOrchestrationVersion.id == int(version_id)
        )
        if version is None or version.orchestration_id != orchestration.id:
            raise OrchestrationSimulationNotFound(
                "Orchestration version not found"
            )
        return version

    draft = orchestrations_repo.get_draft(orchestration.id)
    if draft is not None:
        return draft

    if orchestration.active_version_id is not None:
        version = EventOrchestrationVersion.get_or_none(
            EventOrchestrationVersion.id == orchestration.active_version_id
        )
        if version is not None and version.orchestration_id == orchestration.id:
            return version

    raise OrchestrationSimulationConflict(
        "Orchestration has no draft or published version to simulate"
    )


def normalize_simulation_payload(
    *,
    source: str,
    payload: Any,
    headers: Optional[Mapping[str, Any]] = None,
    event_index: int = 0,
) -> Tuple[str, Dict[str, Any], int]:
    source = str(source or "").strip().lower()
    if source not in SUPPORTED_SIMULATION_SOURCES:
        raise OrchestrationSimulationError(
            "Unsupported simulation source: " + (source or "missing")
        )
    if not isinstance(payload, Mapping):
        raise OrchestrationSimulationError("Simulation payload must be an object")
    _ensure_payload_size(payload, label="Simulation payload")

    try:
        events = normalize_for_source(
            source,
            payload,
            headers=headers,
            route_config={},
            copy_payload=True,
        )
    except UnknownNormalizerSource as exc:
        raise OrchestrationSimulationError(str(exc)) from exc
    except Exception as exc:
        raise OrchestrationSimulationError(
            f"{source} payload could not be normalized"
        ) from exc

    if isinstance(events, Mapping):
        events = [events]
    if not isinstance(events, list) or not events:
        raise OrchestrationSimulationError(
            "The selected normalizer produced no events"
        )
    if event_index < 0 or event_index >= len(events):
        raise OrchestrationSimulationError(
            f"event_index must be between 0 and {len(events) - 1}"
        )

    event = events[event_index]
    if not isinstance(event, Mapping):
        raise OrchestrationSimulationError(
            "The selected normalizer produced an invalid event"
        )
    normalized = copy.deepcopy(dict(event))
    normalized.setdefault("source", source)
    _ensure_payload_size(normalized, label="Normalized event")
    _validate_normalized_event(normalized)
    return source, normalized, len(events)


def prepare_normalized_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(event, Mapping):
        raise OrchestrationSimulationError("normalized_event must be an object")
    normalized = copy.deepcopy(dict(event))
    _ensure_payload_size(normalized, label="Normalized event")
    _validate_normalized_event(normalized)
    return normalized


def _validate_normalized_event(event: Mapping[str, Any]) -> None:
    missing = [
        key
        for key in ("source", "dedup_key", "title")
        if event.get(key) in (None, "")
    ]
    if missing:
        raise OrchestrationSimulationError(
            "Normalized event is missing: " + ", ".join(missing)
        )
    labels = event.get("labels")
    if labels is not None and not isinstance(labels, Mapping):
        raise OrchestrationSimulationError(
            "normalized_event.labels must be an object"
        )


def _entity_summary(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    return {
        "id": getattr(value, "id", None),
        "name": getattr(value, "name", None),
        "slug": getattr(value, "slug", None),
    }


def _selected_summary(
    context: Mapping[str, Any],
    *,
    orchestration: EventOrchestration,
    event: Mapping[str, Any],
    initial_route: Any,
    initial_team: Any,
    initial_service: Any,
) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    try:
        (
            route,
            team,
            service,
            escalation,
            priority,
            notification,
            grouping,
        ) = _resolve_selected_entities(
            context,
            group_id=orchestration.group_id,
            source=event.get("source"),
            fallback_route=initial_route,
            fallback_team=initial_team,
            fallback_service=initial_service,
        )
    except RuntimeOrchestrationError as exc:
        errors.append(str(exc))
        result = context.get("result") or {}
        return {
            "routing": copy.deepcopy(result.get("routing") or {}),
            "policies": copy.deepcopy(result.get("policies") or {}),
            "grouping": copy.deepcopy(result.get("grouping") or {}),
        }, errors

    return {
        "route": _entity_summary(route),
        "team": _entity_summary(team),
        "service": _entity_summary(service),
        "escalation_policy": _entity_summary(escalation),
        "priority_policy": _entity_summary(priority),
        "notification_policy": _entity_summary(notification),
        "grouping": copy.deepcopy(grouping or {}),
    }, errors


def _disposition(context: Mapping[str, Any]) -> Dict[str, Any]:
    result = context.get("result") or {}
    disposition = result.get("disposition") or "process"
    reason = None
    if disposition == "drop":
        reason = result.get("drop_reason")
    elif disposition == "suppress":
        reason = result.get("suppress_reason")
    elif disposition == "pause":
        reason = result.get("pause_reason")
    return {
        "type": disposition,
        "reason": reason,
        "pause_seconds": result.get("pause_seconds"),
        "pause_retrigger": result.get("pause_retrigger"),
    }


def _flatten(
    value: Any,
    *,
    path: str = "",
    output: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if output is None:
        output = {}
    if isinstance(value, Mapping):
        if not value:
            output[path or "$"] = {}
        for key in sorted(value, key=lambda item: str(item)):
            child = f"{path}.{key}" if path else str(key)
            _flatten(value[key], path=child, output=output)
        return output
    if isinstance(value, list):
        if not value:
            output[path or "$"] = []
        for index, item in enumerate(value):
            child = f"{path}[{index}]" if path else f"[{index}]"
            _flatten(item, path=child, output=output)
        return output
    output[path or "$"] = value
    return output


def context_diff(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    maximum = min(
        max(
            int(
                limit
                or getattr(Config, "ORCHESTRATION_SIMULATION_MAX_DIFFS", 512)
            ),
            1,
        ),
        5000,
    )
    left = _flatten(before)
    right = _flatten(after)
    changes = []
    for path in sorted(set(left) | set(right)):
        old = left.get(path)
        new = right.get(path)
        if old == new:
            continue
        changes.append(
            {
                "path": path,
                "before": safe_trace_value(old),
                "after": safe_trace_value(new),
            }
        )
        if len(changes) >= maximum:
            break
    total = sum(
        1
        for path in set(left) | set(right)
        if left.get(path) != right.get(path)
    )
    return {
        "changed": bool(total),
        "total_changes": total,
        "truncated": total > len(changes),
        "changes": changes,
    }


def _simulate_version(
    orchestration: EventOrchestration,
    version: EventOrchestrationVersion,
    event: Mapping[str, Any],
    *,
    evaluated_at: str,
) -> Dict[str, Any]:
    validation = orchestrations_repo.validate_version(version.id)
    response: Dict[str, Any] = {
        "orchestration_id": orchestration.id,
        "version_id": version.id,
        "version_number": version.version_number,
        "version_status": version.status,
        "validation": validation,
    }
    if not validation.get("valid"):
        response["executed"] = False
        response["errors"] = list(validation.get("errors") or [])
        return response

    normalized = prepare_normalized_event(event)
    try:
        route, team, service = _initial_entities(
            normalized,
            orchestration.group_id,
        )
    except RuntimeOrchestrationError as exc:
        response.update(
            {
                "executed": False,
                "errors": [str(exc)],
                "initial_normalized_event": safe_trace_value(normalized),
            }
        )
        return response

    if service is None and orchestration.scope == "service":
        service = orchestration.service
        if team is None and service is not None:
            team = service.team

    context = _build_runtime_context(
        normalized,
        route=route,
        team=team,
        service=service,
    )
    context.setdefault("time", {})["now"] = evaluated_at
    definition = orchestrations_repo.export_version(version.id)
    baseline_context = EventActionState.from_context(context).to_dict()
    started = time.perf_counter()
    try:
        result = execute_rule_tree(definition.get("rules") or [], context)
    except Exception as exc:
        response.update(
            {
                "executed": False,
                "errors": [exc.__class__.__name__],
                "initial_normalized_event": safe_trace_value(normalized),
                "initial_context": safe_trace_value(context),
            }
        )
        return response

    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    selected, selection_errors = _selected_summary(
        result.context,
        orchestration=orchestration,
        event=normalized,
        initial_route=route,
        initial_team=team,
        initial_service=service,
    )
    response.update(
        {
            "executed": True,
            "duration_ms": duration_ms,
            "initial_normalized_event": safe_trace_value(normalized),
            "initial_context": safe_trace_value(context),
            "execution": safe_trace_value(result.to_dict()),
            "final_context": safe_trace_value(result.context),
            "input_output_diff": safe_trace_value(
                context_diff(baseline_context, result.context)
            ),
            "selected": safe_trace_value(selected),
            "disposition": safe_trace_value(_disposition(result.context)),
            "errors": selection_errors,
        }
    )
    return response


def _simulate_resolved_version(
    orchestration: EventOrchestration,
    version: EventOrchestrationVersion,
    event: Mapping[str, Any],
    *,
    active_version: Optional[EventOrchestrationVersion] = None,
    compare_with_active: bool = False,
    selected_normalizer: str = "normalized",
    normalized_event_count: int = 1,
    evaluated_at: Optional[str] = None,
) -> Dict[str, Any]:
    evaluated_at = evaluated_at or utc_now().isoformat()
    result = _simulate_version(
        orchestration,
        version,
        event,
        evaluated_at=evaluated_at,
    )
    result["evaluated_at"] = evaluated_at
    result["selected_normalizer"] = selected_normalizer
    result["normalized_event_count"] = normalized_event_count

    if compare_with_active and active_version is not None:
        active_result = _simulate_version(
            orchestration,
            active_version,
            event,
            evaluated_at=evaluated_at,
        )
        active_result["evaluated_at"] = evaluated_at
        result["active"] = active_result
        if result.get("executed") and active_result.get("executed"):
            result["active_draft_diff"] = context_diff(
                active_result.get("final_context") or {},
                result.get("final_context") or {},
            )
    return safe_trace_value(result)


def _active_version(
    orchestration: EventOrchestration,
) -> Optional[EventOrchestrationVersion]:
    if orchestration.active_version_id is None:
        return None
    active = EventOrchestrationVersion.get_or_none(
        EventOrchestrationVersion.id == orchestration.active_version_id
    )
    if active is None or active.orchestration_id != orchestration.id:
        return None
    return active


def simulate_event(
    orchestration_id: int,
    event: Mapping[str, Any],
    *,
    version_id: Optional[int] = None,
    compare_with_active: bool = False,
    selected_normalizer: str = "normalized",
    normalized_event_count: int = 1,
) -> Dict[str, Any]:
    orchestration = get_orchestration(orchestration_id)
    version = get_simulation_version(orchestration, version_id)
    active = _active_version(orchestration) if compare_with_active else None
    return _simulate_resolved_version(
        orchestration,
        version,
        event,
        active_version=active,
        compare_with_active=compare_with_active,
        selected_normalizer=selected_normalizer,
        normalized_event_count=normalized_event_count,
    )


def _entity_group_id(
    value: Any,
    *,
    depth: int = 0,
    seen: Optional[set[int]] = None,
) -> Optional[int]:
    """Resolve a group through team/route/service relationships safely."""
    if value is None or depth > 3:
        return None
    seen = seen or set()
    identity = id(value)
    if identity in seen:
        return None
    seen.add(identity)

    group_id = getattr(value, "group_id", None)
    if group_id is not None:
        return int(group_id)

    for attribute in ("team", "route", "service", "group"):
        try:
            related = getattr(value, attribute, None)
        except Exception:
            continue
        resolved = _entity_group_id(
            related,
            depth=depth + 1,
            seen=seen,
        )
        if resolved is not None:
            return resolved
    return None


def _alert_group_id(alert: Alert) -> Optional[int]:
    # Alert.group_id points to AlertGroup, not to the tenant Group. Resolve
    # ownership only through the alert's related routing/service entities.
    for attribute in ("team", "route", "service", "group"):
        try:
            related = getattr(alert, attribute, None)
        except Exception:
            continue
        resolved = _entity_group_id(related)
        if resolved is not None:
            return resolved
    return None


def event_from_alert(alert: Alert) -> Dict[str, Any]:
    event = {
        "source": alert.source,
        "external_id": alert.external_id,
        "dedup_key": alert.dedup_key,
        "group_key": alert.group_key,
        "title": alert.title,
        "message": alert.message,
        "severity": alert.severity,
        "labels": copy.deepcopy(alert.labels or {}),
        "payload": copy.deepcopy(alert.payload or {}),
        "status": alert.status,
    }
    if alert.route_id:
        event["forced_route_id"] = alert.route_id
    if alert.team_id:
        event["forced_team_id"] = alert.team_id
    if alert.service_id:
        event["service_id"] = alert.service_id
    return event


def event_from_execution(execution: OrchestrationExecution) -> Dict[str, Any]:
    trace = execution.trace_json or {}
    context = trace.get("initial_context") or {}
    event = copy.deepcopy(context.get("event") or {})
    if context.get("raw") and not event.get("payload"):
        event["payload"] = copy.deepcopy(context.get("raw"))
    event.setdefault("source", execution.source or "webhook")
    event.setdefault(
        "dedup_key",
        execution.event_fingerprint or f"execution:{execution.id}",
    )
    event.setdefault("title", f"Replay execution {execution.id}")
    event.setdefault("labels", {})
    return prepare_normalized_event(event)


def load_replay_inputs(
    orchestration: EventOrchestration,
    *,
    alert_ids: Sequence[int] = (),
    execution_ids: Sequence[int] = (),
) -> List[ReplayInput]:
    maximum = min(
        max(
            int(getattr(Config, "ORCHESTRATION_REPLAY_MAX_EVENTS", 100)),
            1,
        ),
        1000,
    )
    identifiers = len(alert_ids) + len(execution_ids)
    if identifiers < 1:
        raise OrchestrationSimulationError(
            "Replay requires at least one alert_id or execution_id"
        )
    if identifiers > maximum:
        raise OrchestrationSimulationError(
            f"Replay is limited to {maximum} events"
        )

    inputs: List[ReplayInput] = []
    for alert_id in alert_ids:
        alert = Alert.get_or_none(Alert.id == int(alert_id))
        if alert is None:
            raise OrchestrationSimulationNotFound(
                f"Alert {alert_id} not found"
            )
        if _alert_group_id(alert) != orchestration.group_id:
            raise OrchestrationSimulationError(
                f"Alert {alert_id} belongs to another group"
            )
        inputs.append(ReplayInput("alert", alert.id, event_from_alert(alert)))

    for execution_id in execution_ids:
        execution = OrchestrationExecution.get_or_none(
            OrchestrationExecution.id == int(execution_id)
        )
        if execution is None:
            raise OrchestrationSimulationNotFound(
                f"Execution {execution_id} not found"
            )
        if execution.group_id != orchestration.group_id:
            raise OrchestrationSimulationError(
                f"Execution {execution_id} belongs to another group"
            )
        inputs.append(
            ReplayInput(
                "execution",
                execution.id,
                event_from_execution(execution),
            )
        )
    return inputs


def replay_events(
    orchestration_id: int,
    *,
    alert_ids: Sequence[int] = (),
    execution_ids: Sequence[int] = (),
    version_id: Optional[int] = None,
    compare_with_active: bool = False,
) -> Dict[str, Any]:
    orchestration = get_orchestration(orchestration_id)
    inputs = load_replay_inputs(
        orchestration,
        alert_ids=alert_ids,
        execution_ids=execution_ids,
    )
    version = get_simulation_version(orchestration, version_id)
    active = _active_version(orchestration) if compare_with_active else None
    evaluated_at = utc_now().isoformat()
    results = []
    for item in inputs:
        try:
            simulation = _simulate_resolved_version(
                orchestration,
                version,
                item.event,
                active_version=active,
                compare_with_active=compare_with_active,
                selected_normalizer="stored_normalized_event",
                evaluated_at=evaluated_at,
            )
            results.append(
                {
                    "input": {"kind": item.kind, "id": item.id},
                    "ok": True,
                    "simulation": simulation,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "input": {"kind": item.kind, "id": item.id},
                    "ok": False,
                    "error": exc.__class__.__name__,
                }
            )
    successful = [item for item in results if item["ok"]]
    dispositions: Dict[str, int] = {}
    changed_from_active = 0
    for item in successful:
        simulation = item.get("simulation") or {}
        disposition = (simulation.get("disposition") or {}).get("type") or "process"
        dispositions[disposition] = dispositions.get(disposition, 0) + 1
        if (simulation.get("active_draft_diff") or {}).get("changed"):
            changed_from_active += 1

    drop_count = dispositions.get("drop", 0)
    drop_percentage = (
        round((drop_count / len(successful)) * 100, 2)
        if successful
        else 0.0
    )
    warning_threshold = min(
        max(
            int(
                getattr(
                    Config,
                    "ORCHESTRATION_REPLAY_DROP_WARNING_PERCENT",
                    20,
                )
            ),
            0,
        ),
        100,
    )
    warnings = []
    if successful and drop_percentage >= warning_threshold and drop_count:
        warnings.append(
            {
                "code": "high_drop_rate",
                "message": (
                    f"Draft would drop {drop_percentage}% of replayed events"
                ),
                "drop_percentage": drop_percentage,
                "threshold_percentage": warning_threshold,
            }
        )

    return {
        "orchestration_id": orchestration.id,
        "version_id": version.id,
        "active_version_id": active.id if active is not None else None,
        "evaluated_at": evaluated_at,
        "count": len(results),
        "successful": len(successful),
        "failed": sum(1 for item in results if not item["ok"]),
        "production_state_modified": False,
        "summary": {
            "dispositions": dispositions,
            "drop_percentage": drop_percentage,
            "changed_from_active": changed_from_active,
        },
        "warnings": warnings,
        "results": results,
    }


def serialize_execution(
    execution: OrchestrationExecution,
    *,
    include_trace: bool = False,
) -> Dict[str, Any]:
    created_at = execution.created_at
    expires_at = execution.expires_at
    trace = execution.trace_json or {}
    result = {
        "id": execution.id,
        "uid": str(execution.uid),
        "group_id": execution.group_id,
        "orchestration_id": execution.orchestration_id,
        "version_id": execution.version_id,
        "source": execution.source,
        "integration_name": execution.integration_name,
        "event_fingerprint": execution.event_fingerprint,
        "mode": trace.get("mode"),
        "compatibility_mode": trace.get("compatibility_mode"),
        "applied": bool(trace.get("applied")),
        "error": safe_trace_value(trace.get("error")),
        "rejected_reason": safe_trace_value(trace.get("rejected_reason")),
        "disposition": execution.disposition,
        "matched_rule_count": execution.matched_rule_count,
        "duration_ms": execution.duration_ms,
        "alert_id": execution.alert_id,
        "alert_group_id": execution.alert_group_id,
        "created_at": _iso_datetime(created_at),
        "expires_at": _iso_datetime(expires_at),
    }
    if include_trace:
        result["trace"] = safe_trace_value(execution.trace_json or {})
    return result


def list_executions(
    orchestration_id: int,
    *,
    limit: int = 50,
    include_trace: bool = False,
) -> List[Dict[str, Any]]:
    orchestration = get_orchestration(orchestration_id)
    maximum = min(max(int(limit), 1), 200)
    rows = (
        OrchestrationExecution.select()
        .where(OrchestrationExecution.orchestration == orchestration.id)
        .order_by(OrchestrationExecution.id.desc())
        .limit(maximum)
    )
    return [
        serialize_execution(row, include_trace=include_trace)
        for row in rows
    ]


def _candidate_actual_values(trace: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    result = (trace.get("result") or {}).get("context") or {}
    candidate_result = result.get("result") or {}
    candidate_routing = candidate_result.get("routing") or {}
    candidate_event = result.get("event") or {}
    candidate = {
        "route_id": (
            candidate_routing.get("route_id")
            or (result.get("route") or {}).get("id")
        ),
        "team_id": (
            candidate_routing.get("team_id")
            or (result.get("team") or {}).get("id")
        ),
        "service_id": (
            candidate_routing.get("service_id")
            or (result.get("service") or {}).get("id")
        ),
        "severity": candidate_event.get("severity"),
        "title": candidate_event.get("title"),
        "group_key": (
            (candidate_result.get("grouping") or {}).get("group_key")
            or candidate_event.get("group_key")
        ),
        "disposition": candidate_result.get("disposition") or "process",
    }
    actual = copy.deepcopy(trace.get("actual_result") or {})
    return candidate, actual


def shadow_metrics(
    orchestration_id: int,
    *,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    orchestration = get_orchestration(orchestration_id)
    maximum = min(
        max(
            int(
                limit
                or getattr(
                    Config,
                    "ORCHESTRATION_SHADOW_METRICS_MAX_EXECUTIONS",
                    5000,
                )
            ),
            1,
        ),
        10000,
    )
    rows = (
        OrchestrationExecution.select()
        .where(OrchestrationExecution.orchestration == orchestration.id)
        .order_by(OrchestrationExecution.id.desc())
        .limit(maximum)
    )
    metrics = {
        "executions": 0,
        "matched": 0,
        "errors": 0,
        "rejected": 0,
        "comparable_executions": 0,
        "not_comparable": 0,
        "routing_changes": 0,
        "team_changes": 0,
        "service_changes": 0,
        "severity_changes": 0,
        "title_changes": 0,
        "grouping_changes": 0,
        "potential_drops": 0,
        "potential_suppressions": 0,
        "potential_pauses": 0,
    }
    first_at = None
    last_at = None
    for row in rows:
        trace = row.trace_json or {}
        if trace.get("mode") != "shadow":
            continue
        metrics["executions"] += 1
        if row.matched_rule_count:
            metrics["matched"] += 1
        execution_error = trace.get("error")
        rejected_reason = trace.get("rejected_reason")
        if execution_error:
            metrics["errors"] += 1
        if rejected_reason:
            metrics["rejected"] += 1

        candidate, actual = _candidate_actual_values(trace)
        comparable = bool(trace.get("result")) and not execution_error and not rejected_reason
        if actual and comparable:
            metrics["comparable_executions"] += 1
            if candidate.get("route_id") != actual.get("route_id"):
                metrics["routing_changes"] += 1
            if candidate.get("team_id") != actual.get("team_id"):
                metrics["team_changes"] += 1
            if candidate.get("service_id") != actual.get("service_id"):
                metrics["service_changes"] += 1
            if candidate.get("severity") != actual.get("severity"):
                metrics["severity_changes"] += 1
            if candidate.get("title") != actual.get("title"):
                metrics["title_changes"] += 1
            if candidate.get("group_key") != actual.get("group_key"):
                metrics["grouping_changes"] += 1
        else:
            metrics["not_comparable"] += 1
        disposition = candidate.get("disposition")
        if disposition == "drop":
            metrics["potential_drops"] += 1
        elif disposition == "suppress":
            metrics["potential_suppressions"] += 1
        elif disposition == "pause":
            metrics["potential_pauses"] += 1
        created_at = parse_datetime(row.created_at)
        if created_at:
            first_at = min(first_at, created_at) if first_at else created_at
            last_at = max(last_at, created_at) if last_at else created_at

    return {
        "orchestration_id": orchestration.id,
        "mode": orchestration.mode,
        "limit": maximum,
        "first_execution_at": first_at.isoformat() if first_at else None,
        "last_execution_at": last_at.isoformat() if last_at else None,
        "metrics": metrics,
    }


__all__ = [
    "SUPPORTED_SIMULATION_SOURCES",
    "OrchestrationSimulationConflict",
    "OrchestrationSimulationError",
    "OrchestrationSimulationNotFound",
    "context_diff",
    "get_orchestration",
    "list_executions",
    "normalize_simulation_payload",
    "prepare_normalized_event",
    "replay_events",
    "shadow_metrics",
    "simulate_event",
]
