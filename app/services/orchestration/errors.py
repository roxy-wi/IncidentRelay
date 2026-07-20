"""Safe error types for the Event Orchestration evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ValidationIssue:
    """A structured validation problem suitable for API and UI responses."""

    path: str
    code: str
    message: str
    severity: str = "error"

    def to_dict(self) -> Dict[str, str]:
        return {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


class OrchestrationEvaluationError(ValueError):
    """Base class for deterministic evaluator failures."""

    code = "evaluation_error"

    def __init__(self, message: str, *, path: Optional[str] = None):
        self.path = path
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "path": self.path,
        }


class FieldResolutionError(OrchestrationEvaluationError):
    code = "invalid_field_reference"


class ConditionValidationError(OrchestrationEvaluationError):
    code = "invalid_condition"


class RegexSafetyError(OrchestrationEvaluationError):
    code = "unsafe_regex"


class TemplateValidationError(OrchestrationEvaluationError):
    code = "invalid_template"


class ExtractionError(OrchestrationEvaluationError):
    code = "variable_extraction_failed"
