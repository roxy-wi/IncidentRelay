"""Deterministic Event Orchestration action execution.

The action layer mutates an isolated JSON-compatible event state. It never
loads database entities, performs network I/O or calls provider integrations.
Static entity references are validated by the control-plane repository before
publication and are resolved by a later ingestion-integration workstream.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .errors import OrchestrationEvaluationError, ValidationIssue
from .fields import MISSING, resolve_field
from .templates import render_template, validate_template
from .variables import EXTRACTION_TYPES, extract_variables, validate_extractor


MAX_ACTIONS_PER_RULE = 128
MAX_ACTION_VALUE_DEPTH = 16
MAX_ACTION_COLLECTION_ITEMS = 512
MAX_ACTION_VALUE_BYTES = 65_536
MAX_LABELS = 256
MAX_LABEL_NAME_LENGTH = 128
MAX_CUSTOM_FIELD_NAME_LENGTH = 128
MAX_NOTE_LENGTH = 8_192
MAX_PAUSE_SECONDS = 604_800
MAX_GROUP_WINDOW_SECONDS = 86_400

FAILURE_MODES = frozenset({"continue", "stop_rule", "stop_orchestration"})
PROCESS_DISPOSITIONS = frozenset({"process", "suppress", "pause", "drop"})
EVENT_ACTIONS = frozenset({"trigger", "resolve"})
TRACE_LEVELS = frozenset({"full", "compact", "disabled"})

_TEXT_FIELD_ACTIONS = {
    "set_title": "title",
    "set_message": "message",
    "set_description": "description",
    "set_severity": "severity",
    "set_priority": "priority",
    "set_dedup_key": "dedup_key",
    "set_group_key": "group_key",
}
_ROUTING_ACTIONS = {
    "set_route": ("route", "route_id"),
    "set_team": ("team", "team_id"),
    "set_service": ("service", "service_id"),
}
_POLICY_ACTIONS = {
    "set_escalation_policy": "escalation_policy_id",
    "set_notification_policy": "notification_policy_id",
    "set_priority_policy": "priority_policy_id",
}
SUPPORTED_ACTION_TYPES = frozenset(
    set(EXTRACTION_TYPES)
    | set(_TEXT_FIELD_ACTIONS)
    | set(_ROUTING_ACTIONS)
    | set(_POLICY_ACTIONS)
    | {
        "set_event_action",
        "set_trace_level",
        "set_label",
        "remove_label",
        "set_custom_field",
        "remove_custom_field",
        "set_grouping",
        "add_note",
        "suppress",
        "drop",
        "pause",
        "enqueue_webhook",
    }
)

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")


class ActionValidationError(OrchestrationEvaluationError):
    code = "invalid_action"


@dataclass
class EventActionState:
    """Mutable internal state; caller-owned mappings are always deep-copied."""

    event: Dict[str, Any]
    raw: Dict[str, Any]
    variables: Dict[str, Any]
    route: Dict[str, Any]
    service: Dict[str, Any]
    team: Dict[str, Any]
    integration: Dict[str, Any]
    time: Dict[str, Any]
    result: Dict[str, Any]

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> "EventActionState":
        event = _json_copy(context.get("event") or {}, path="event")
        labels = context.get("labels")
        if labels is None:
            labels = event.get("labels") or {}
        event["labels"] = _json_copy(labels, path="labels")

        result = _json_copy(context.get("result") or {}, path="result")
        result.setdefault("disposition", "process")
        result.setdefault("suppress_notifications", False)
        result.setdefault("trace_level", None)
        result.setdefault("dropped", False)
        result.setdefault("pause_seconds", None)
        result.setdefault("pause_retrigger", "preserve")
        result.setdefault("suppress_reason", None)
        result.setdefault("pause_reason", None)
        result.setdefault("drop_reason", None)
        result.setdefault("routing", {})
        result.setdefault("policies", {})
        result.setdefault("grouping", {})
        result.setdefault("notes", [])
        result.setdefault("webhooks", [])

        if result["disposition"] not in PROCESS_DISPOSITIONS:
            raise ActionValidationError("result.disposition is invalid", path="result.disposition")
        if not isinstance(result["routing"], dict):
            raise ActionValidationError("result.routing must be an object", path="result.routing")
        if not isinstance(result["policies"], dict):
            raise ActionValidationError("result.policies must be an object", path="result.policies")
        if not isinstance(result["grouping"], dict):
            raise ActionValidationError("result.grouping must be an object", path="result.grouping")
        if not isinstance(result["notes"], list):
            raise ActionValidationError("result.notes must be a list", path="result.notes")
        if not isinstance(result["webhooks"], list):
            raise ActionValidationError("result.webhooks must be a list", path="result.webhooks")

        return cls(
            event=event,
            raw=_json_copy(context.get("raw") or {}, path="raw"),
            variables=_json_copy(context.get("variables") or {}, path="variables"),
            route=_json_copy(context.get("route") or {}, path="route"),
            service=_json_copy(context.get("service") or {}, path="service"),
            team=_json_copy(context.get("team") or {}, path="team"),
            integration=_json_copy(context.get("integration") or {}, path="integration"),
            time=_json_copy(context.get("time") or {}, path="time"),
            result=result,
        )

    @property
    def labels(self) -> Dict[str, Any]:
        labels = self.event.setdefault("labels", {})
        if not isinstance(labels, dict):
            raise ActionValidationError("event.labels must be an object", path="event.labels")
        return labels

    def context(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "labels": self.labels,
            "raw": self.raw,
            "variables": self.variables,
            "route": self.route,
            "service": self.service,
            "team": self.team,
            "integration": self.integration,
            "time": self.time,
            "result": self.result,
        }

    def to_dict(self) -> Dict[str, Any]:
        return _json_copy(self.context(), path="context")


@dataclass(frozen=True)
class ActionStepResult:
    index: int
    action_type: str
    success: bool
    code: str
    reason: str
    before: Any = None
    after: Any = None
    references: Tuple[str, ...] = field(default_factory=tuple)
    failure_mode: str = "continue"
    outcome: str = "continue"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "type": self.action_type,
            "success": self.success,
            "code": self.code,
            "reason": self.reason,
            "before": _trace_value(self.before),
            "after": _trace_value(self.after),
            "references": list(self.references),
            "failure_mode": self.failure_mode,
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class ActionExecutionResult:
    state: EventActionState
    steps: Tuple[ActionStepResult, ...]
    outcome: str = "continue"

    @property
    def context(self) -> Dict[str, Any]:
        return self.state.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context": self.context,
            "steps": [step.to_dict() for step in self.steps],
            "outcome": self.outcome,
        }


def _trace_value(value: Any) -> Any:
    if value is MISSING:
        return None
    if isinstance(value, str):
        return value if len(value) <= 512 else value[:512] + "…"
    if isinstance(value, list):
        return [_trace_value(item) for item in value[:32]]
    if isinstance(value, tuple):
        return [_trace_value(item) for item in value[:32]]
    if isinstance(value, dict):
        return {str(key): _trace_value(item) for key, item in list(value.items())[:32]}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return "<unsupported>"


def _validate_json_value(value: Any, *, path: str, depth: int = 0) -> None:
    if depth > MAX_ACTION_VALUE_DEPTH:
        raise ActionValidationError("action value exceeds the nesting limit", path=path)
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ActionValidationError("action value cannot contain non-finite numbers", path=path)
        return
    if isinstance(value, list):
        if len(value) > MAX_ACTION_COLLECTION_ITEMS:
            raise ActionValidationError("action value list exceeds the item limit", path=path)
        for index, child in enumerate(value):
            _validate_json_value(child, path=f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_ACTION_COLLECTION_ITEMS:
            raise ActionValidationError("action value object exceeds the item limit", path=path)
        for key, child in value.items():
            if not isinstance(key, str):
                raise ActionValidationError("action object keys must be strings", path=path)
            _validate_json_value(child, path=f"{path}.{key}", depth=depth + 1)
        return
    raise ActionValidationError("action value must be JSON-compatible", path=path)


def _json_copy(value: Any, *, path: str) -> Any:
    _validate_json_value(value, path=path)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:  # defensive; validation above is explicit
        raise ActionValidationError("action value must be JSON-compatible", path=path) from exc
    if len(encoded.encode("utf-8")) > MAX_ACTION_VALUE_BYTES:
        raise ActionValidationError("action value exceeds the size limit", path=path)
    return copy.deepcopy(value)


def _action_value_sources(action: Mapping[str, Any]) -> List[str]:
    return [key for key in ("value", "value_from", "template") if key in action]


def _resolve_value(
    action: Mapping[str, Any],
    state: EventActionState,
    *,
    path: str,
    required: bool = True,
) -> Tuple[Any, Tuple[str, ...]]:
    sources = _action_value_sources(action)
    if not sources:
        if required:
            raise ActionValidationError("action requires value, value_from or template", path=path)
        return None, ()
    if len(sources) != 1:
        raise ActionValidationError("action value sources are mutually exclusive", path=path)

    source = sources[0]
    if source == "value_from":
        resolution = resolve_field(state.context(), action["value_from"])
        if not resolution.found:
            raise ActionValidationError(
                f"source field {resolution.normalized_reference!r} does not exist",
                path=f"{path}.value_from",
            )
        return _json_copy(resolution.value, path=f"{path}.value_from"), (
            resolution.normalized_reference,
        )

    value = action[source]
    if source == "template" or (
        isinstance(value, str) and ("{{" in value or "}}" in value)
    ):
        if not isinstance(value, str):
            raise ActionValidationError("template must be a string", path=f"{path}.{source}")
        rendered = render_template(value, state.context())
        return rendered.value, rendered.references
    return _json_copy(value, path=f"{path}.{source}"), ()


def _scalar_text(value: Any, *, path: str, allow_empty: bool = True) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif value is None:
        text = ""
    elif isinstance(value, (str, int, float)):
        text = str(value)
    else:
        raise ActionValidationError("action value must be scalar", path=path)
    if not allow_empty and not text.strip():
        raise ActionValidationError("action value cannot be empty", path=path)
    return text


def _validate_name(value: Any, *, path: str, max_length: int) -> None:
    if not isinstance(value, str) or not value:
        raise ActionValidationError("name is required", path=path)
    if len(value) > max_length:
        raise ActionValidationError("name exceeds the size limit", path=path)
    if not _NAME.fullmatch(value):
        raise ActionValidationError(
            "name must start with a letter or underscore and contain only letters, numbers, dot, colon, dash or underscore",
            path=path,
        )


def _positive_id(value: Any, *, path: str) -> int:
    if isinstance(value, bool):
        raise ActionValidationError("reference id must be a positive integer", path=path)
    try:
        identifier = int(value)
    except (TypeError, ValueError) as exc:
        raise ActionValidationError("reference id must be a positive integer", path=path) from exc
    if identifier <= 0:
        raise ActionValidationError("reference id must be a positive integer", path=path)
    return identifier


def _static_reference(action: Mapping[str, Any], keys: Sequence[str], *, path: str) -> int:
    present = [key for key in keys if key in action and action[key] not in (None, "")]
    params = action.get("params")
    if isinstance(params, dict):
        present.extend(
            f"params.{key}" for key in keys if key in params and params[key] not in (None, "")
        )
    if len(present) != 1:
        raise ActionValidationError("action requires exactly one static reference id", path=path)
    source = present[0]
    if source.startswith("params."):
        if not isinstance(params, dict):
            raise ActionValidationError(
                "action requires exactly one static reference id",
                path=path,
            )
        value = params[source.split(".", 1)[1]]
    else:
        value = action[source]
    return _positive_id(value, path=f"{path}.{source}")


def _validate_value_source(action: Mapping[str, Any], *, path: str, required: bool = True) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    sources = _action_value_sources(action)
    if required and not sources:
        issues.append(ValidationIssue(path, "missing_action_value", "action requires value, value_from or template"))
    if len(sources) > 1:
        issues.append(ValidationIssue(path, "conflicting_action_value", "action value sources are mutually exclusive"))
    if "value_from" in action:
        try:
            resolve_field({root: {} for root in ("event", "labels", "raw", "variables", "route", "service", "team", "integration", "time", "result")}, action["value_from"])
        except ValueError as exc:
            issues.append(ValidationIssue(f"{path}.value_from", "invalid_field_reference", str(exc)))
    for source in ("value", "template"):
        value = action.get(source)
        if isinstance(value, str) and (source == "template" or "{{" in value or "}}" in value):
            issues.extend(validate_template(value, path=f"{path}.{source}"))
    return issues


def validate_action(action: Any, *, path: str = "action") -> List[ValidationIssue]:
    if not isinstance(action, dict):
        return [ValidationIssue(path, "invalid_action", "action must be an object")]
    action_type = action.get("type")
    if action_type not in SUPPORTED_ACTION_TYPES:
        return [
            ValidationIssue(
                f"{path}.type",
                "unsupported_action",
                f"unsupported orchestration action {action_type!r}",
            )
        ]
    if action_type in EXTRACTION_TYPES:
        return validate_extractor(action, path=path)

    issues: List[ValidationIssue] = []
    failure_mode = action.get("on_failure", "continue")
    if failure_mode not in FAILURE_MODES:
        issues.append(
            ValidationIssue(
                f"{path}.on_failure",
                "invalid_failure_mode",
                "on_failure must be continue, stop_rule or stop_orchestration",
            )
        )

    if action_type in _TEXT_FIELD_ACTIONS or action_type in {"set_event_action", "set_label", "set_custom_field", "add_note"}:
        issues.extend(_validate_value_source(action, path=path))

    if action_type == "set_event_action" and "value" in action:
        if action["value"] not in EVENT_ACTIONS:
            issues.append(
                ValidationIssue(f"{path}.value", "invalid_event_action", "event action must be trigger or resolve")
            )
    elif action_type == "set_trace_level":
        level = action.get("level")
        if level not in TRACE_LEVELS:
            issues.append(
                ValidationIssue(
                    f"{path}.level",
                    "invalid_trace_level",
                    "trace level must be full, compact or disabled",
                )
            )
    elif action_type in {"set_label", "remove_label"}:
        try:
            _validate_name(action.get("name", action.get("label")), path=f"{path}.name", max_length=MAX_LABEL_NAME_LENGTH)
        except ActionValidationError as exc:
            issues.append(ValidationIssue(exc.path or f"{path}.name", exc.code, str(exc)))
    elif action_type in {"set_custom_field", "remove_custom_field"}:
        try:
            _validate_name(action.get("name", action.get("field")), path=f"{path}.name", max_length=MAX_CUSTOM_FIELD_NAME_LENGTH)
        except ActionValidationError as exc:
            issues.append(ValidationIssue(exc.path or f"{path}.name", exc.code, str(exc)))
    elif action_type in _ROUTING_ACTIONS:
        _, id_key = _ROUTING_ACTIONS[action_type]
        try:
            _static_reference(action, (id_key, "value"), path=path)
        except ActionValidationError as exc:
            issues.append(ValidationIssue(exc.path or path, exc.code, str(exc)))
    elif action_type in _POLICY_ACTIONS:
        id_key = _POLICY_ACTIONS[action_type]
        try:
            _static_reference(action, (id_key, "policy_id", "value"), path=path)
        except ActionValidationError as exc:
            issues.append(ValidationIssue(exc.path or path, exc.code, str(exc)))
    elif action_type == "set_grouping":
        keys = {"dedup_key", "group_key", "window_seconds", "strategy"}
        if not any(key in action for key in keys):
            issues.append(ValidationIssue(path, "empty_grouping_action", "set_grouping requires at least one grouping field"))
        if "window_seconds" in action:
            value = action["window_seconds"]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_GROUP_WINDOW_SECONDS:
                issues.append(ValidationIssue(f"{path}.window_seconds", "invalid_group_window", "grouping window must be between 0 and 86400 seconds"))
        for key in ("dedup_key", "group_key", "strategy"):
            value = action.get(key)
            if isinstance(value, str) and ("{{" in value or "}}" in value):
                issues.extend(validate_template(value, path=f"{path}.{key}"))
    elif action_type == "pause":
        seconds = action.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= MAX_PAUSE_SECONDS:
            issues.append(ValidationIssue(f"{path}.seconds", "invalid_pause_duration", "pause duration must be between 1 and 604800 seconds"))
        retrigger = action.get("retrigger", "preserve")
        if retrigger not in {"preserve", "reset"}:
            issues.append(ValidationIssue(f"{path}.retrigger", "invalid_pause_retrigger", "pause retrigger must be preserve or reset"))

    elif action_type == "enqueue_webhook":
        action_id = action.get("action_id", action.get("webhook_action_id"))
        if isinstance(action_id, bool) or not isinstance(action_id, int) or action_id <= 0:
            issues.append(ValidationIssue(
                f"{path}.action_id",
                "invalid_webhook_action",
                "enqueue_webhook requires a positive integer action_id",
            ))

    if action_type in {"suppress", "pause", "drop"}:
        reason = action.get("reason")
        if reason is not None and not isinstance(reason, str):
            issues.append(ValidationIssue(f"{path}.reason", "invalid_disposition_reason", "disposition reason must be a string"))
        elif isinstance(reason, str) and ("{{" in reason or "}}" in reason):
            issues.extend(validate_template(reason, path=f"{path}.reason"))

    return issues


def validate_action_list(actions: Any, *, path: str = "actions") -> List[ValidationIssue]:
    if not isinstance(actions, list):
        return [ValidationIssue(path, "invalid_actions", "actions must be a list")]
    if len(actions) > MAX_ACTIONS_PER_RULE:
        return [ValidationIssue(path, "action_limit", "rule has too many actions")]
    issues: List[ValidationIssue] = []
    for index, action in enumerate(actions):
        issues.extend(validate_action(action, path=f"{path}[{index}]"))
    return issues


def _execute_grouping(action: Mapping[str, Any], state: EventActionState, *, path: str) -> Tuple[Any, Any, Tuple[str, ...]]:
    before = copy.deepcopy(state.result.get("grouping") or {})
    grouping: MutableMapping[str, Any] = state.result.setdefault("grouping", {})
    references: List[str] = []

    for key in ("dedup_key", "group_key", "strategy"):
        if key not in action:
            continue
        value = action[key]
        if isinstance(value, str) and ("{{" in value or "}}" in value):
            rendered = render_template(value, state.context())
            value = rendered.value
            references.extend(rendered.references)
        value = _scalar_text(value, path=f"{path}.{key}", allow_empty=False)
        grouping[key] = value
        if key in {"dedup_key", "group_key"}:
            state.event[key] = value

    if "window_seconds" in action:
        seconds = action["window_seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= MAX_GROUP_WINDOW_SECONDS:
            raise ActionValidationError("grouping window must be between 0 and 86400 seconds", path=f"{path}.window_seconds")
        grouping["window_seconds"] = seconds

    return before, copy.deepcopy(grouping), tuple(references)


def _disposition_reason(
    action: Mapping[str, Any],
    state: EventActionState,
    *,
    path: str,
) -> Tuple[Optional[str], Tuple[str, ...]]:
    reason = action.get("reason")
    if reason in (None, ""):
        return None, ()
    references: Tuple[str, ...] = ()
    if "{{" in reason or "}}" in reason:
        rendered = render_template(reason, state.context())
        reason = rendered.value
        references = rendered.references
    reason = _scalar_text(reason, path=f"{path}.reason", allow_empty=True)
    if len(reason) > MAX_NOTE_LENGTH:
        raise ActionValidationError(
            "disposition reason exceeds the size limit",
            path=f"{path}.reason",
        )
    return reason or None, references


def _execute_action(action: Mapping[str, Any], state: EventActionState, *, path: str) -> Tuple[Any, Any, Tuple[str, ...], str]:
    action_type = action["type"]

    if action_type in _TEXT_FIELD_ACTIONS:
        target = _TEXT_FIELD_ACTIONS[action_type]
        before = state.event.get(target)
        value, references = _resolve_value(action, state, path=path)
        state.event[target] = _scalar_text(value, path=f"{path}.value")
        return before, state.event[target], references, "continue"

    if action_type == "set_event_action":
        before = state.event.get("event_action")
        value, references = _resolve_value(action, state, path=path)
        normalized = _scalar_text(value, path=f"{path}.value", allow_empty=False).lower()
        if normalized not in EVENT_ACTIONS:
            raise ActionValidationError("event action must be trigger or resolve", path=f"{path}.value")
        state.event["event_action"] = normalized
        return before, normalized, references, "continue"

    if action_type == "set_trace_level":
        before = state.result.get("trace_level")
        level = str(action.get("level") or "").strip().lower()
        if level not in TRACE_LEVELS:
            raise ActionValidationError(
                "trace level must be full, compact or disabled",
                path=f"{path}.level",
            )
        state.result["trace_level"] = level
        return before, level, (), "continue"

    if action_type == "set_label":
        name = action.get("name", action.get("label"))
        _validate_name(name, path=f"{path}.name", max_length=MAX_LABEL_NAME_LENGTH)
        labels = state.labels
        if name not in labels and len(labels) >= MAX_LABELS:
            raise ActionValidationError("event label count exceeds the limit", path=f"{path}.name")
        before = labels.get(name, MISSING)
        value, references = _resolve_value(action, state, path=path)
        labels[name] = _scalar_text(value, path=f"{path}.value")
        return before, labels[name], references, "continue"

    if action_type == "remove_label":
        name = action.get("name", action.get("label"))
        _validate_name(name, path=f"{path}.name", max_length=MAX_LABEL_NAME_LENGTH)
        before = state.labels.get(name, MISSING)
        state.labels.pop(name, None)
        return before, MISSING, (), "continue"

    if action_type == "set_custom_field":
        name = action.get("name", action.get("field"))
        _validate_name(name, path=f"{path}.name", max_length=MAX_CUSTOM_FIELD_NAME_LENGTH)
        details = state.event.setdefault("custom_details", {})
        if not isinstance(details, dict):
            raise ActionValidationError("event.custom_details must be an object", path="event.custom_details")
        before = details.get(name, MISSING)
        value, references = _resolve_value(action, state, path=path)
        details[name] = _json_copy(value, path=f"{path}.value")
        return before, details[name], references, "continue"

    if action_type == "remove_custom_field":
        name = action.get("name", action.get("field"))
        _validate_name(name, path=f"{path}.name", max_length=MAX_CUSTOM_FIELD_NAME_LENGTH)
        details = state.event.setdefault("custom_details", {})
        if not isinstance(details, dict):
            raise ActionValidationError("event.custom_details must be an object", path="event.custom_details")
        before = details.get(name, MISSING)
        details.pop(name, None)
        return before, MISSING, (), "continue"

    if action_type in _ROUTING_ACTIONS:
        root, id_key = _ROUTING_ACTIONS[action_type]
        identifier = _static_reference(action, (id_key, "value"), path=path)
        target = getattr(state, root)
        before = copy.deepcopy(target)
        target.clear()
        target["id"] = identifier
        state.result.setdefault("routing", {})[id_key] = identifier
        return before, copy.deepcopy(target), (), "continue"

    if action_type in _POLICY_ACTIONS:
        id_key = _POLICY_ACTIONS[action_type]
        identifier = _static_reference(action, (id_key, "policy_id", "value"), path=path)
        policies = state.result.setdefault("policies", {})
        before = policies.get(id_key, MISSING)
        policies[id_key] = identifier
        return before, identifier, (), "continue"

    if action_type == "set_grouping":
        before, after, references = _execute_grouping(action, state, path=path)
        return before, after, references, "continue"

    if action_type == "add_note":
        before = list(state.result.setdefault("notes", []))
        value, references = _resolve_value(action, state, path=path)
        note = _scalar_text(value, path=f"{path}.value", allow_empty=False)
        if len(note) > MAX_NOTE_LENGTH:
            raise ActionValidationError("note exceeds the size limit", path=f"{path}.value")
        state.result["notes"].append(note)
        return before, list(state.result["notes"]), references, "continue"

    if action_type == "enqueue_webhook":
        action_id = action.get("action_id", action.get("webhook_action_id"))
        if isinstance(action_id, bool) or not isinstance(action_id, int) or action_id <= 0:
            raise ActionValidationError(
                "enqueue_webhook requires a positive integer action_id",
                path=f"{path}.action_id",
            )
        webhooks = state.result.setdefault("webhooks", [])
        before = list(webhooks)
        request = {"action_id": action_id}
        webhooks.append(request)
        return before, request, (), "continue"

    if action_type == "suppress":
        reason, references = _disposition_reason(action, state, path=path)
        before = {
            "disposition": state.result.get("disposition"),
            "suppress_notifications": state.result.get("suppress_notifications"),
            "suppress_reason": state.result.get("suppress_reason"),
        }
        state.result["disposition"] = "suppress"
        state.result["suppress_notifications"] = True
        state.result["suppress_reason"] = reason
        return before, {
            "disposition": "suppress",
            "suppress_notifications": True,
            "reason": reason,
        }, references, "continue"

    if action_type == "pause":
        seconds = action.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= MAX_PAUSE_SECONDS:
            raise ActionValidationError("pause duration must be between 1 and 604800 seconds", path=f"{path}.seconds")
        retrigger = action.get("retrigger", "preserve")
        if retrigger not in {"preserve", "reset"}:
            raise ActionValidationError("pause retrigger must be preserve or reset", path=f"{path}.retrigger")
        reason, references = _disposition_reason(action, state, path=path)
        before = {
            "disposition": state.result.get("disposition"),
            "pause_seconds": state.result.get("pause_seconds"),
            "pause_retrigger": state.result.get("pause_retrigger"),
            "pause_reason": state.result.get("pause_reason"),
        }
        state.result["disposition"] = "pause"
        state.result["pause_seconds"] = seconds
        state.result["pause_retrigger"] = retrigger
        state.result["pause_reason"] = reason
        return before, {
            "disposition": "pause",
            "pause_seconds": seconds,
            "retrigger": retrigger,
            "reason": reason,
        }, references, "continue"

    if action_type == "drop":
        reason, references = _disposition_reason(action, state, path=path)
        before = {
            "disposition": state.result.get("disposition"),
            "dropped": state.result.get("dropped"),
            "drop_reason": state.result.get("drop_reason"),
        }
        state.result["disposition"] = "drop"
        state.result["dropped"] = True
        state.result["suppress_notifications"] = True
        state.result["drop_reason"] = reason
        return before, {
            "disposition": "drop",
            "dropped": True,
            "reason": reason,
        }, references, "stop_orchestration"

    raise ActionValidationError(f"unsupported action {action_type!r}", path=f"{path}.type")


def execute_actions(
    actions: Sequence[Mapping[str, Any]],
    context: Optional[Mapping[str, Any]] = None,
    *,
    state: Optional[EventActionState] = None,
) -> ActionExecutionResult:
    """Execute actions in order and return state plus an explainable trace."""

    action_list = list(actions)
    issues = validate_action_list(action_list)
    # Static validation errors are programming/configuration errors. Runtime
    # missing-field/template failures are recorded per action below.
    if issues:
        first = issues[0]
        raise ActionValidationError(first.message, path=first.path)
    if state is None:
        state = EventActionState.from_context(context or {})

    steps: List[ActionStepResult] = []
    outcome = "continue"

    for index, action in enumerate(action_list):
        action_type = action["type"]
        failure_mode = action.get("on_failure", "continue")
        path = f"actions[{index}]"

        if action_type in EXTRACTION_TYPES:
            extraction = extract_variables(
                [action],
                state.context(),
                initial_variables=state.variables,
            )
            state.variables.clear()
            state.variables.update(extraction.variables)
            extraction_step = extraction.steps[0]
            steps.append(
                ActionStepResult(
                    index=index,
                    action_type=action_type,
                    success=extraction_step.success,
                    code=extraction_step.code,
                    reason=extraction_step.reason,
                    before=None,
                    after=dict(extraction_step.variables),
                    references=(),
                    failure_mode=extraction_step.failure_mode,
                    outcome=extraction.outcome,
                )
            )
            if extraction.outcome in {"stop_rule", "stop_orchestration"}:
                outcome = extraction.outcome
                break
            continue

        try:
            before, after, references, action_outcome = _execute_action(action, state, path=path)
            steps.append(
                ActionStepResult(
                    index=index,
                    action_type=action_type,
                    success=True,
                    code="action_applied",
                    reason="action applied",
                    before=before,
                    after=after,
                    references=references,
                    failure_mode=failure_mode,
                    outcome=action_outcome,
                )
            )
            if action_outcome == "stop_orchestration":
                outcome = action_outcome
                break
        except (OrchestrationEvaluationError, ValueError) as exc:
            steps.append(
                ActionStepResult(
                    index=index,
                    action_type=action_type,
                    success=False,
                    code=getattr(exc, "code", "action_failed"),
                    reason=str(exc),
                    before=None,
                    after=None,
                    references=(),
                    failure_mode=failure_mode,
                    outcome=failure_mode,
                )
            )
            if failure_mode in {"stop_rule", "stop_orchestration"}:
                outcome = failure_mode
                break

    return ActionExecutionResult(state=state, steps=tuple(steps), outcome=outcome)


__all__ = [
    "ActionExecutionResult",
    "ActionStepResult",
    "ActionValidationError",
    "EventActionState",
    "SUPPORTED_ACTION_TYPES",
    "TRACE_LEVELS",
    "execute_actions",
    "validate_action",
    "validate_action_list",
]
