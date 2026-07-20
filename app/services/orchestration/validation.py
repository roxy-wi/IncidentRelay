"""Publication-time validation for orchestration conditions and templates."""

from __future__ import annotations

from typing import Any, Dict, List

from .conditions import validate_condition_tree
from .errors import ValidationIssue
from .templates import find_templates, validate_template
from .variables import EXTRACTION_TYPES, validate_extractor


def validate_rule_definition(
    condition_tree: Any,
    actions: Any,
    *,
    path: str = "rule",
) -> Dict[str, List[ValidationIssue]]:
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []

    errors.extend(validate_condition_tree(condition_tree, path=f"{path}.condition_tree"))
    if not isinstance(actions, list):
        errors.append(
            ValidationIssue(f"{path}.actions", "invalid_actions", "actions must be a list")
        )
        return {"errors": errors, "warnings": warnings}

    for index, action in enumerate(actions):
        action_path = f"{path}.actions[{index}]"
        if not isinstance(action, dict):
            errors.append(
                ValidationIssue(action_path, "invalid_action", "action must be an object")
            )
            continue
        if action.get("type") in EXTRACTION_TYPES:
            errors.extend(validate_extractor(action, path=action_path))
        for template_path, template in find_templates(action, path=action_path):
            errors.extend(validate_template(template, path=template_path))

    def dedupe(items: List[ValidationIssue]) -> List[ValidationIssue]:
        result: List[ValidationIssue] = []
        seen = set()
        for item in items:
            key = (item.path, item.code, item.message, item.severity)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    return {"errors": dedupe(errors), "warnings": dedupe(warnings)}


def issues_to_messages(issues: List[ValidationIssue]) -> List[str]:
    return [f"{issue.path}: {issue.message}" for issue in issues]
