"""Deterministic ordered rule-tree execution for Event Orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .actions import ActionStepResult, EventActionState, execute_actions, validate_action_list
from .conditions import ConditionResult, evaluate_condition_tree, validate_condition_tree
from .errors import ConditionValidationError


MAX_RULE_DEPTH = 20
MAX_RULE_NODES = 512
VALID_PROCESSING_MODES = frozenset(
    {"continue", "stop", "evaluate_children", "children_then_continue"}
)


@dataclass(frozen=True)
class RuleExecutionResult:
    path: str
    name: str
    enabled: bool
    matched: bool
    processing_mode: str
    condition: Optional[ConditionResult] = None
    actions: Tuple[ActionStepResult, ...] = field(default_factory=tuple)
    children: Tuple["RuleExecutionResult", ...] = field(default_factory=tuple)
    outcome: str = "continue"
    code: str = "rule_evaluated"
    reason: str = "rule evaluated"

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "path": self.path,
            "name": self.name,
            "enabled": self.enabled,
            "matched": self.matched,
            "processing_mode": self.processing_mode,
            "actions": [step.to_dict() for step in self.actions],
            "children": [child.to_dict() for child in self.children],
            "outcome": self.outcome,
            "code": self.code,
            "reason": self.reason,
        }
        if self.condition is not None:
            result["condition"] = self.condition.to_dict()
        return result


@dataclass(frozen=True)
class OrchestrationExecutionResult:
    state: EventActionState
    rules: Tuple[RuleExecutionResult, ...]
    outcome: str
    matched_rule_count: int
    stopped_at: Optional[str] = None

    @property
    def context(self) -> Dict[str, Any]:
        return self.state.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context": self.context,
            "rules": [rule.to_dict() for rule in self.rules],
            "outcome": self.outcome,
            "matched_rule_count": self.matched_rule_count,
            "stopped_at": self.stopped_at,
        }


@dataclass
class _EngineCounters:
    nodes: int = 0
    matched: int = 0
    stopped_at: Optional[str] = None


def _validate_rules(rules: Any, *, path: str = "rules", depth: int = 0, counters: Optional[_EngineCounters] = None) -> None:
    if counters is None:
        counters = _EngineCounters()
    if depth > MAX_RULE_DEPTH:
        raise ConditionValidationError("rule tree exceeds the depth limit", path=path)
    if not isinstance(rules, list):
        raise ConditionValidationError("rules must be a list", path=path)
    for index, rule in enumerate(rules):
        rule_path = f"{path}[{index}]"
        counters.nodes += 1
        if counters.nodes > MAX_RULE_NODES:
            raise ConditionValidationError("rule tree exceeds the node limit", path=rule_path)
        if not isinstance(rule, dict):
            raise ConditionValidationError("rule must be an object", path=rule_path)
        mode = rule.get("processing_mode", "continue")
        if mode not in VALID_PROCESSING_MODES:
            raise ConditionValidationError("invalid rule processing_mode", path=f"{rule_path}.processing_mode")
        condition_issues = validate_condition_tree(
            rule.get("condition_tree") or {},
            path=f"{rule_path}.condition_tree",
        )
        if condition_issues:
            first = condition_issues[0]
            raise ConditionValidationError(first.message, path=first.path)
        actions = rule.get("actions", [])
        if not isinstance(actions, list):
            raise ConditionValidationError("rule actions must be a list", path=f"{rule_path}.actions")
        action_issues = validate_action_list(actions, path=f"{rule_path}.actions")
        if action_issues:
            first = action_issues[0]
            raise ConditionValidationError(first.message, path=first.path)
        children = rule.get("children", [])
        if not isinstance(children, list):
            raise ConditionValidationError("rule children must be a list", path=f"{rule_path}.children")
        _validate_rules(children, path=f"{rule_path}.children", depth=depth + 1, counters=counters)


def _execute_level(
    rules: Sequence[Mapping[str, Any]],
    state: EventActionState,
    *,
    path: str,
    depth: int,
    counters: _EngineCounters,
) -> Tuple[List[RuleExecutionResult], str]:
    traces: List[RuleExecutionResult] = []

    for index, rule in enumerate(rules):
        rule_path = f"{path}[{index}]"
        name = str(rule.get("name") or f"Rule {index + 1}")
        enabled = bool(rule.get("enabled", True))
        mode = rule.get("processing_mode", "continue")

        if not enabled:
            traces.append(
                RuleExecutionResult(
                    path=rule_path,
                    name=name,
                    enabled=False,
                    matched=False,
                    processing_mode=mode,
                    code="rule_disabled",
                    reason="rule is disabled",
                )
            )
            continue

        condition = evaluate_condition_tree(rule.get("condition_tree") or {}, state.context())
        if not condition.matched:
            traces.append(
                RuleExecutionResult(
                    path=rule_path,
                    name=name,
                    enabled=True,
                    matched=False,
                    processing_mode=mode,
                    condition=condition,
                    code="rule_not_matched",
                    reason="rule condition did not match",
                )
            )
            continue

        counters.matched += 1
        action_result = execute_actions(rule.get("actions") or [], state=state)
        child_traces: List[RuleExecutionResult] = []
        local_outcome = action_result.outcome

        if local_outcome == "stop_orchestration":
            counters.stopped_at = rule_path
            traces.append(
                RuleExecutionResult(
                    path=rule_path,
                    name=name,
                    enabled=True,
                    matched=True,
                    processing_mode=mode,
                    condition=condition,
                    actions=action_result.steps,
                    outcome="stop_orchestration",
                    code="rule_stopped_orchestration",
                    reason="an action stopped orchestration processing",
                )
            )
            return traces, "stop_orchestration"

        children = rule.get("children") or []
        if mode in {"evaluate_children", "children_then_continue"} and children:
            child_traces, child_outcome = _execute_level(
                children,
                state,
                path=f"{rule_path}.children",
                depth=depth + 1,
                counters=counters,
            )
            if child_outcome == "stop_orchestration":
                counters.stopped_at = counters.stopped_at or rule_path
                traces.append(
                    RuleExecutionResult(
                        path=rule_path,
                        name=name,
                        enabled=True,
                        matched=True,
                        processing_mode=mode,
                        condition=condition,
                        actions=action_result.steps,
                        children=tuple(child_traces),
                        outcome="stop_orchestration",
                        code="child_stopped_orchestration",
                        reason="a child rule stopped orchestration processing",
                    )
                )
                return traces, "stop_orchestration"

        if mode == "stop":
            counters.stopped_at = rule_path
            rule_outcome = "stop_orchestration"
            code = "processing_mode_stop"
            reason = "rule processing_mode stopped orchestration processing"
        elif mode == "evaluate_children":
            counters.stopped_at = rule_path
            rule_outcome = "stop_orchestration"
            code = "children_evaluated_then_stop"
            reason = "child rules were evaluated and sibling processing stopped"
        else:
            rule_outcome = local_outcome
            code = "rule_matched"
            reason = "rule matched and actions were evaluated"

        traces.append(
            RuleExecutionResult(
                path=rule_path,
                name=name,
                enabled=True,
                matched=True,
                processing_mode=mode,
                condition=condition,
                actions=action_result.steps,
                children=tuple(child_traces),
                outcome=rule_outcome,
                code=code,
                reason=reason,
            )
        )

        if rule_outcome == "stop_orchestration":
            return traces, "stop_orchestration"

    return traces, "continue"


def execute_rule_tree(
    rules: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> OrchestrationExecutionResult:
    """Evaluate a published rule definition against an isolated event copy."""

    rule_list = list(rules)
    _validate_rules(rule_list)
    state = EventActionState.from_context(context)
    counters = _EngineCounters()
    traces, outcome = _execute_level(
        rule_list,
        state,
        path="rules",
        depth=0,
        counters=counters,
    )
    if state.result.get("dropped"):
        outcome = "drop"
    elif outcome == "stop_orchestration":
        outcome = "stop"
    else:
        outcome = "continue"
    return OrchestrationExecutionResult(
        state=state,
        rules=tuple(traces),
        outcome=outcome,
        matched_rule_count=counters.matched,
        stopped_at=counters.stopped_at,
    )


__all__ = [
    "OrchestrationExecutionResult",
    "RuleExecutionResult",
    "execute_rule_tree",
]
