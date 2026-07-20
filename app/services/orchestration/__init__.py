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
