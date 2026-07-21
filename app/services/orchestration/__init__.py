"""Event Orchestration condition, extraction and template services."""

from .conditions import ConditionResult, evaluate_condition_tree, validate_condition_tree
from .evaluator import RuleEvaluationResult, evaluate_rule
from .fields import MISSING, build_context, resolve_field
from .templates import TemplateRenderResult, render_template, validate_template
from .variables import ExtractionResult, extract_variables, validate_extractors

__all__ = [
    "ConditionResult",
    "ExtractionResult",
    "MISSING",
    "RuleEvaluationResult",
    "TemplateRenderResult",
    "build_context",
    "evaluate_condition_tree",
    "evaluate_rule",
    "extract_variables",
    "render_template",
    "resolve_field",
    "validate_condition_tree",
    "validate_extractors",
    "validate_template",
]

# BEGIN EVENT ORCHESTRATION WS3 EXPORTS
from .actions import (
    ActionExecutionResult,
    ActionStepResult,
    ActionValidationError,
    EventActionState,
    execute_actions,
    validate_action,
    validate_action_list,
)
from .engine import (
    OrchestrationExecutionResult,
    RuleExecutionResult,
    execute_rule_tree,
)

__all__ += [
    "ActionExecutionResult",
    "ActionStepResult",
    "ActionValidationError",
    "EventActionState",
    "OrchestrationExecutionResult",
    "RuleExecutionResult",
    "execute_actions",
    "execute_rule_tree",
    "validate_action",
    "validate_action_list",
]
# END EVENT ORCHESTRATION WS3 EXPORTS
