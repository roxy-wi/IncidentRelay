"""A restricted interpolation engine for Event Orchestration.

This is deliberately not Jinja. Expressions are limited to safe field
references followed by whitelisted string filters with literal arguments.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .errors import TemplateValidationError, ValidationIssue
from .fields import normalize_field_reference, resolve_field
from .limits import (
    MAX_TEMPLATE_EXPRESSION_LENGTH,
    MAX_TEMPLATE_EXPRESSIONS,
    MAX_TEMPLATE_FILTERS,
    MAX_TEMPLATE_LENGTH,
    MAX_TEMPLATE_OUTPUT_LENGTH,
)


_EXPRESSION = re.compile(r"{{(.*?)}}", re.DOTALL)
_FILTER = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\((.*)\))?$", re.DOTALL)
_ALLOWED_FILTERS = frozenset({"lower", "upper", "trim", "default", "replace", "truncate"})


@dataclass(frozen=True)
class ParsedExpression:
    field: str
    filters: Tuple[Tuple[str, Tuple[Any, ...]], ...]


@dataclass(frozen=True)
class TemplateRenderResult:
    value: str
    references: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "references": list(self.references)}


def _split_pipeline(expression: str) -> List[str]:
    parts: List[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(expression):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise TemplateValidationError("unbalanced filter parentheses")
        elif char == "|" and depth == 0:
            parts.append(expression[start:index].strip())
            start = index + 1
    if quote is not None or depth != 0:
        raise TemplateValidationError("unbalanced template expression")
    parts.append(expression[start:].strip())
    return parts


def _literal_arguments(raw: str | None) -> Tuple[Any, ...]:
    if raw is None or not raw.strip():
        return ()
    try:
        value = ast.literal_eval(f"({raw},)")
    except (SyntaxError, ValueError) as exc:
        raise TemplateValidationError("filter arguments must be string, number, boolean or null literals") from exc
    if not isinstance(value, tuple):  # pragma: no cover
        raise TemplateValidationError("invalid filter arguments")
    for item in value:
        if not isinstance(item, (str, int, float, bool, type(None))):
            raise TemplateValidationError("filter arguments cannot contain collections or objects")
    return value


def _validate_filter(name: str, args: Tuple[Any, ...]) -> None:
    if name not in _ALLOWED_FILTERS:
        raise TemplateValidationError(f"unsupported template filter {name!r}")
    required = {
        "lower": (0, 0),
        "upper": (0, 0),
        "trim": (0, 0),
        "default": (1, 1),
        "replace": (2, 2),
        "truncate": (1, 1),
    }[name]
    if not required[0] <= len(args) <= required[1]:
        raise TemplateValidationError(
            f"filter {name} expects {required[0]} argument(s)"
        )
    if name == "replace" and not all(isinstance(arg, str) for arg in args):
        raise TemplateValidationError("replace arguments must be strings")
    if name == "truncate":
        length = args[0]
        if isinstance(length, bool) or not isinstance(length, int) or length < 0:
            raise TemplateValidationError("truncate length must be a non-negative integer")
        if length > MAX_TEMPLATE_OUTPUT_LENGTH:
            raise TemplateValidationError("truncate length exceeds the output limit")


def parse_expression(expression: str) -> ParsedExpression:
    expression = expression.strip()
    if not expression:
        raise TemplateValidationError("template expression cannot be empty")
    if len(expression) > MAX_TEMPLATE_EXPRESSION_LENGTH:
        raise TemplateValidationError("template expression exceeds the size limit")
    parts = _split_pipeline(expression)
    field = normalize_field_reference(parts[0])
    if len(parts) - 1 > MAX_TEMPLATE_FILTERS:
        raise TemplateValidationError("template expression has too many filters")

    filters: List[Tuple[str, Tuple[Any, ...]]] = []
    for raw_filter in parts[1:]:
        match = _FILTER.fullmatch(raw_filter)
        if not match:
            raise TemplateValidationError(f"invalid template filter syntax {raw_filter!r}")
        name = match.group(1)
        args = _literal_arguments(match.group(2))
        _validate_filter(name, args)
        filters.append((name, args))
    return ParsedExpression(field=field, filters=tuple(filters))


def validate_template(template: Any, *, path: str = "template") -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if not isinstance(template, str):
        return [ValidationIssue(path, "invalid_template_type", "template must be a string")]
    if len(template) > MAX_TEMPLATE_LENGTH:
        return [ValidationIssue(path, "template_size_limit", "template exceeds the size limit")]

    matches = list(_EXPRESSION.finditer(template))
    if len(matches) > MAX_TEMPLATE_EXPRESSIONS:
        issues.append(
            ValidationIssue(path, "template_expression_limit", "template has too many expressions")
        )
    # Any leftover delimiter indicates malformed syntax.
    stripped = _EXPRESSION.sub("", template)
    if "{{" in stripped or "}}" in stripped:
        issues.append(
            ValidationIssue(path, "unbalanced_template_delimiter", "template contains unbalanced delimiters")
        )

    for index, match in enumerate(matches):
        try:
            parse_expression(match.group(1))
        except (TemplateValidationError, ValueError) as exc:
            code = getattr(exc, "code", "invalid_template")
            issues.append(
                ValidationIssue(f"{path}.expression[{index}]", code, str(exc))
            )
    return issues


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise TemplateValidationError("templates can only render scalar values")


def _apply_filter(value: Any, name: str, args: Sequence[Any], *, missing: bool) -> Tuple[Any, bool]:
    if name == "default":
        if missing or value is None or value == "":
            return args[0], False
        return value, missing
    if missing:
        return value, missing
    text = _stringify(value)
    if name == "lower":
        return text.lower(), False
    if name == "upper":
        return text.upper(), False
    if name == "trim":
        return text.strip(), False
    if name == "replace":
        return text.replace(args[0], args[1]), False
    if name == "truncate":
        return text[: args[0]], False
    raise TemplateValidationError(f"unsupported template filter {name!r}")


def render_template(
    template: str,
    context: Mapping[str, Any],
    *,
    max_output_length: int = MAX_TEMPLATE_OUTPUT_LENGTH,
) -> TemplateRenderResult:
    issues = validate_template(template)
    if issues:
        first = issues[0]
        raise TemplateValidationError(first.message, path=first.path)
    if max_output_length < 0 or max_output_length > MAX_TEMPLATE_OUTPUT_LENGTH:
        raise TemplateValidationError("invalid template output limit")

    references: List[str] = []
    output: List[str] = []
    cursor = 0
    length = 0

    def append(value: str) -> None:
        nonlocal length
        length += len(value)
        if length > max_output_length:
            raise TemplateValidationError("rendered template exceeds the output limit")
        output.append(value)

    for match in _EXPRESSION.finditer(template):
        append(template[cursor : match.start()])
        parsed = parse_expression(match.group(1))
        references.append(parsed.field)
        resolution = resolve_field(context, parsed.field)
        value = resolution.value
        missing = not resolution.found
        for name, args in parsed.filters:
            value, missing = _apply_filter(value, name, args, missing=missing)
        if missing:
            raise TemplateValidationError(
                f"template field {parsed.field!r} does not exist",
                path=parsed.field,
            )
        append(_stringify(value))
        cursor = match.end()
    append(template[cursor:])
    return TemplateRenderResult("".join(output), tuple(references))


def find_templates(value: Any, *, path: str = "value") -> Iterable[Tuple[str, str]]:
    """Yield ``(path, template)`` for strings containing template syntax."""

    if isinstance(value, str):
        if "{{" in value or "}}" in value:
            yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from find_templates(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from find_templates(child, path=f"{path}[{index}]")
