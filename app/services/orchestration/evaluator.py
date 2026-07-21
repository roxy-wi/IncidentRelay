"""High-level evaluator facade used by simulation and the future action engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

from .conditions import ConditionResult, evaluate_condition_tree
from .fields import build_context
from .templates import TemplateRenderResult, render_template
from .variables import ExtractionResult, extract_variables


@dataclass(frozen=True)
class RuleEvaluationResult:
    matched: bool
    condition: ConditionResult
    variables: Mapping[str, Any]
    extraction_steps: Tuple[Mapping[str, Any], ...]
    extraction_outcome: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matched": self.matched,
            "condition": self.condition.to_dict(),
            "variables": dict(self.variables),
            "extraction_steps": list(self.extraction_steps),
            "extraction_outcome": self.extraction_outcome,
        }


def evaluate_rule(
    *,
    condition_tree: Mapping[str, Any],
    context: Mapping[str, Any],
    extractors: Sequence[Mapping[str, Any]] = (),
) -> RuleEvaluationResult:
    condition = evaluate_condition_tree(condition_tree, context)
    if not condition.matched or not extractors:
        return RuleEvaluationResult(
            condition.matched,
            condition,
            dict(context.get("variables") or {}),
            (),
            "continue",
        )

    extraction = extract_variables(extractors, context)
    return RuleEvaluationResult(
        condition.matched,
        condition,
        extraction.variables,
        tuple(step.to_dict() for step in extraction.steps),
        extraction.outcome,
    )


__all__ = [
    "ConditionResult",
    "ExtractionResult",
    "RuleEvaluationResult",
    "TemplateRenderResult",
    "build_context",
    "evaluate_condition_tree",
    "evaluate_rule",
    "extract_variables",
    "render_template",
]

# BEGIN EVENT ORCHESTRATION WS3 EXPORTS
from .actions import ActionExecutionResult, EventActionState, execute_actions
from .engine import OrchestrationExecutionResult, execute_rule_tree

__all__ += [
    "ActionExecutionResult",
    "EventActionState",
    "OrchestrationExecutionResult",
    "execute_actions",
    "execute_rule_tree",
]
# END EVENT ORCHESTRATION WS3 EXPORTS
