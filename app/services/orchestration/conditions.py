"""Deterministic nested condition-tree evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import ConditionValidationError, RegexSafetyError, ValidationIssue
from .fields import MISSING, resolve_field, validate_field_reference
from .limits import MAX_CONDITION_DEPTH, MAX_CONDITION_NODES, MAX_TRACE_VALUE_LENGTH
from .regex import bounded_regex_input, compile_safe_regex, validate_regex_pattern


LOGICAL_KEYS = frozenset({"all", "any", "none"})
OPERATOR_ALIASES = {
    "eq": "equals",
    "ne": "not_equals",
    "gt": "greater_than",
    "lt": "less_than",
    "gte": "greater_or_equal",
    "lte": "less_or_equal",
}
SUPPORTED_OPERATORS = frozenset(
    {
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
        "regex",
        "not_regex",
        "in",
        "not_in",
        "exists",
        "not_exists",
        "greater_than",
        "less_than",
        "greater_or_equal",
        "less_or_equal",
        "is_true",
        "is_false",
    }
)


@dataclass(frozen=True)
class ConditionResult:
    matched: bool
    code: str
    reason: str
    path: str = "$"
    node_type: str = "condition"
    field: Optional[str] = None
    operator: Optional[str] = None
    expected: Any = MISSING
    actual: Any = None
    found: Optional[bool] = None
    children: Tuple["ConditionResult", ...] = dataclass_field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "matched": self.matched,
            "code": self.code,
            "reason": self.reason,
            "path": self.path,
            "node_type": self.node_type,
        }
        if self.field is not None:
            result["field"] = self.field
        if self.operator is not None:
            result["operator"] = self.operator
        if self.found is not None:
            result["found"] = self.found
        if self.expected is not MISSING:
            result["expected"] = _trace_value(self.expected)
        if self.actual is not None or self.found is True:
            result["actual"] = _trace_value(self.actual)
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result


def _trace_value(value: Any) -> Any:
    if value is MISSING:
        return None
    if isinstance(value, str) and len(value) > MAX_TRACE_VALUE_LENGTH:
        return value[:MAX_TRACE_VALUE_LENGTH] + "…"
    if isinstance(value, list):
        return [_trace_value(item) for item in value[:32]]
    if isinstance(value, tuple):
        return [_trace_value(item) for item in value[:32]]
    if isinstance(value, dict):
        items = list(value.items())[:32]
        return {str(key): _trace_value(item) for key, item in items}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return "<unsupported>"


def normalize_operator(operator: Any) -> str:
    if not isinstance(operator, str):
        raise ConditionValidationError("condition operator must be a string")
    normalized = OPERATOR_ALIASES.get(operator.strip(), operator.strip())
    if normalized not in SUPPORTED_OPERATORS:
        raise ConditionValidationError(f"unsupported condition operator {operator!r}")
    return normalized


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InvalidOperation
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidOperation
        result = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise InvalidOperation
        result = Decimal(text)
    else:
        raise InvalidOperation
    if not result.is_finite():
        raise InvalidOperation
    return result


def _coerce_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError("value is not deterministically boolean")


def _equal(left: Any, right: Any) -> bool:
    if left is MISSING or right is MISSING:
        return False
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float, Decimal)) or isinstance(
        right, (int, float, Decimal)
    ):
        try:
            return _decimal(left) == _decimal(right)
        except InvalidOperation:
            return False
    if left is None or right is None:
        return left is right
    return type(left) is type(right) and left == right


def _contains(container: Any, expected: Any) -> bool:
    if isinstance(container, str):
        return isinstance(expected, str) and expected in container
    if isinstance(container, Mapping):
        return expected in container
    if isinstance(container, Sequence) and not isinstance(
        container, (str, bytes, bytearray)
    ):
        return any(_equal(item, expected) for item in container)
    return False


def _in(actual: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        return actual in expected
    if isinstance(expected, Sequence) and not isinstance(
        expected, (str, bytes, bytearray)
    ):
        return any(_equal(actual, item) for item in expected)
    return False


def _evaluate_operator(operator: str, actual: Any, expected: Any, found: bool) -> Tuple[bool, str]:
    if operator == "exists":
        return found, "field_exists" if found else "field_missing"
    if operator == "not_exists":
        return not found, "field_missing" if not found else "field_exists"
    if not found:
        return False, "field_missing"

    if operator == "equals":
        matched = _equal(actual, expected)
    elif operator == "not_equals":
        matched = not _equal(actual, expected)
    elif operator == "contains":
        matched = _contains(actual, expected)
    elif operator == "not_contains":
        matched = not _contains(actual, expected)
    elif operator == "starts_with":
        matched = isinstance(actual, str) and isinstance(expected, str) and actual.startswith(expected)
    elif operator == "ends_with":
        matched = isinstance(actual, str) and isinstance(expected, str) and actual.endswith(expected)
    elif operator in {"regex", "not_regex"}:
        regex = compile_safe_regex(expected)
        matched = regex.search(bounded_regex_input(actual)) is not None
        if operator == "not_regex":
            matched = not matched
    elif operator == "in":
        matched = _in(actual, expected)
    elif operator == "not_in":
        matched = not _in(actual, expected)
    elif operator in {
        "greater_than",
        "less_than",
        "greater_or_equal",
        "less_or_equal",
    }:
        try:
            left = _decimal(actual)
            right = _decimal(expected)
        except InvalidOperation:
            return False, "numeric_coercion_failed"
        matched = {
            "greater_than": left > right,
            "less_than": left < right,
            "greater_or_equal": left >= right,
            "less_or_equal": left <= right,
        }[operator]
    elif operator in {"is_true", "is_false"}:
        try:
            boolean = _coerce_boolean(actual)
        except ValueError:
            return False, "boolean_coercion_failed"
        matched = boolean if operator == "is_true" else not boolean
    else:  # pragma: no cover - protected by validation
        raise ConditionValidationError(f"unsupported operator {operator}")

    return matched, "condition_matched" if matched else "condition_mismatched"


def validate_condition_tree(tree: Any, *, path: str = "condition_tree") -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    node_count = 0

    def visit(node: Any, node_path: str, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_CONDITION_NODES:
            issues.append(
                ValidationIssue(node_path, "condition_node_limit", "condition tree has too many nodes")
            )
            return
        if depth > MAX_CONDITION_DEPTH:
            issues.append(
                ValidationIssue(node_path, "condition_depth_limit", "condition tree is nested too deeply")
            )
            return
        if not isinstance(node, dict):
            issues.append(
                ValidationIssue(node_path, "invalid_condition_node", "condition node must be an object")
            )
            return
        if not node:
            return  # Explicit catch-all rule.

        logical = [key for key in LOGICAL_KEYS if key in node]
        if logical:
            if len(logical) != 1 or len(node) != 1:
                issues.append(
                    ValidationIssue(
                        node_path,
                        "ambiguous_condition_node",
                        "logical condition nodes must contain exactly one of all, any or none",
                    )
                )
                return
            key = logical[0]
            children = node[key]
            if not isinstance(children, list):
                issues.append(
                    ValidationIssue(
                        f"{node_path}.{key}",
                        "invalid_condition_children",
                        f"{key} must contain a list",
                    )
                )
                return
            for index, child in enumerate(children):
                visit(child, f"{node_path}.{key}[{index}]", depth + 1)
            return

        allowed = {"field", "operator", "value"}
        unknown = sorted(set(node) - allowed)
        if unknown:
            issues.append(
                ValidationIssue(
                    node_path,
                    "unknown_condition_keys",
                    "unknown condition keys: " + ", ".join(unknown),
                )
            )
        if "field" not in node:
            issues.append(ValidationIssue(node_path, "missing_field", "condition field is required"))
        else:
            issues.extend(validate_field_reference(node["field"], path=f"{node_path}.field"))
        if "operator" not in node:
            issues.append(
                ValidationIssue(node_path, "missing_operator", "condition operator is required")
            )
            return
        try:
            operator = normalize_operator(node["operator"])
        except ConditionValidationError as exc:
            issues.append(ValidationIssue(f"{node_path}.operator", exc.code, str(exc)))
            return

        no_value = {"exists", "not_exists", "is_true", "is_false"}
        if operator not in no_value and "value" not in node:
            issues.append(
                ValidationIssue(node_path, "missing_condition_value", f"operator {operator} requires value")
            )
        if operator in {"regex", "not_regex"} and "value" in node:
            try:
                validate_regex_pattern(node["value"])
            except RegexSafetyError as exc:
                issues.append(ValidationIssue(f"{node_path}.value", exc.code, str(exc)))
        if operator in {"in", "not_in"} and "value" in node:
            value = node["value"]
            if not isinstance(value, (list, tuple, dict)):
                issues.append(
                    ValidationIssue(
                        f"{node_path}.value",
                        "invalid_collection",
                        f"operator {operator} requires a list or object value",
                    )
                )
        if operator in {
            "greater_than",
            "less_than",
            "greater_or_equal",
            "less_or_equal",
        } and "value" in node:
            try:
                _decimal(node["value"])
            except InvalidOperation:
                issues.append(
                    ValidationIssue(
                        f"{node_path}.value",
                        "invalid_numeric_value",
                        f"operator {operator} requires a finite numeric value",
                    )
                )

    visit(tree, path, 0)
    # Avoid emitting the same global limit many times.
    deduped: List[ValidationIssue] = []
    seen = set()
    for issue in issues:
        key = (issue.path, issue.code, issue.message)
        if key not in seen:
            seen.add(key)
            deduped.append(issue)
    return deduped


def evaluate_condition_tree(
    tree: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    validate: bool = True,
    path: str = "$",
) -> ConditionResult:
    """Evaluate every node so Explain traces contain matches and mismatches."""

    if validate:
        issues = validate_condition_tree(tree)
        if issues:
            first = issues[0]
            raise ConditionValidationError(first.message, path=first.path)

    def visit(node: Mapping[str, Any], node_path: str) -> ConditionResult:
        if not node:
            return ConditionResult(True, "catch_all", "empty condition matches all events", path=node_path, node_type="all")

        logical = next((key for key in ("all", "any", "none") if key in node), None)
        if logical is not None:
            children = tuple(
                visit(child, f"{node_path}.{logical}[{index}]")
                for index, child in enumerate(node[logical])
            )
            child_matches = [child.matched for child in children]
            if logical == "all":
                matched = all(child_matches)
            elif logical == "any":
                matched = any(child_matches)
            else:
                matched = not any(child_matches)
            return ConditionResult(
                matched=matched,
                code=f"{logical}_{'matched' if matched else 'mismatched'}",
                reason=f"{logical} group {'matched' if matched else 'did not match'}",
                path=node_path,
                node_type=logical,
                children=children,
            )

        field_reference = node["field"]
        operator = normalize_operator(node["operator"])
        expected = node["value"] if "value" in node else MISSING
        resolution = resolve_field(context, field_reference)
        try:
            matched, code = _evaluate_operator(
                operator,
                resolution.value,
                expected,
                resolution.found,
            )
            reason = code.replace("_", " ")
        except RegexSafetyError as exc:
            matched = False
            code = exc.code
            reason = str(exc)
        return ConditionResult(
            matched=matched,
            code=code,
            reason=reason,
            path=node_path,
            field=resolution.normalized_reference,
            operator=operator,
            expected=expected,
            actual=None if not resolution.found else resolution.value,
            found=resolution.found,
        )

    return visit(tree, path)
