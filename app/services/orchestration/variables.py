"""Restricted variable extraction for Event Orchestration."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .errors import ExtractionError, RegexSafetyError, ValidationIssue
from .fields import MISSING, normalize_field_reference, resolve_field
from .limits import (
    MAX_JSON_PATH_LENGTH,
    MAX_SPLIT_PARTS,
    MAX_VARIABLE_NAME_LENGTH,
    MAX_VARIABLE_VALUE_LENGTH,
    MAX_VARIABLES,
)
from .regex import bounded_regex_input, compile_safe_regex, validate_regex_pattern
from .templates import render_template, validate_template


VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EXTRACTION_TYPES = frozenset(
    {
        "extract_regex",
        "copy_field",
        "copy_to_variable",
        "json_path",
        "split",
        "set_variable",
        "static",
        "lowercase",
        "uppercase",
        "trim",
    }
)
FAILURE_MODES = frozenset({"continue", "stop_rule", "stop_orchestration"})


@dataclass(frozen=True)
class ExtractionStepResult:
    index: int
    extractor_type: str
    success: bool
    code: str
    reason: str
    variables: Mapping[str, Any]
    failure_mode: str = "continue"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "type": self.extractor_type,
            "success": self.success,
            "code": self.code,
            "reason": self.reason,
            "variables": dict(self.variables),
            "failure_mode": self.failure_mode,
        }


@dataclass(frozen=True)
class ExtractionResult:
    variables: Mapping[str, Any]
    steps: Tuple[ExtractionStepResult, ...]
    outcome: str = "continue"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variables": dict(self.variables),
            "steps": [step.to_dict() for step in self.steps],
            "outcome": self.outcome,
        }


def _validate_variable_name(name: Any) -> Optional[str]:
    if not isinstance(name, str) or not name:
        return "variable name is required"
    if len(name) > MAX_VARIABLE_NAME_LENGTH:
        return "variable name exceeds the size limit"
    if not VARIABLE_NAME.fullmatch(name):
        return "variable name must start with a letter or underscore and contain only letters, numbers and underscores"
    return None


def _extractor_target(extractor: Mapping[str, Any]) -> Any:
    return extractor.get("name", extractor.get("target"))


def _validate_json_path(path: Any) -> Optional[str]:
    if not isinstance(path, str) or not path:
        return "JSON path is required"
    if len(path) > MAX_JSON_PATH_LENGTH:
        return "JSON path exceeds the size limit"
    try:
        _parse_json_path(path)
    except ExtractionError as exc:
        return str(exc)
    return None


def validate_extractor(extractor: Any, *, path: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if not isinstance(extractor, dict):
        return [ValidationIssue(path, "invalid_extractor", "extractor must be an object")]
    extractor_type = extractor.get("type")
    if extractor_type not in EXTRACTION_TYPES:
        return [
            ValidationIssue(
                f"{path}.type",
                "unsupported_extractor",
                f"unsupported variable extractor {extractor_type!r}",
            )
        ]
    failure_mode = extractor.get("on_failure", "continue")
    if failure_mode not in FAILURE_MODES:
        issues.append(
            ValidationIssue(
                f"{path}.on_failure",
                "invalid_failure_mode",
                "on_failure must be continue, stop_rule or stop_orchestration",
            )
        )

    if extractor_type == "extract_regex":
        source = extractor.get("source")
        try:
            normalize_field_reference(source)
        except ValueError as exc:
            issues.append(ValidationIssue(f"{path}.source", "invalid_field_reference", str(exc)))
        compiled = None
        try:
            normalized_pattern = validate_regex_pattern(extractor.get("pattern"))
            compiled = re.compile(normalized_pattern)
        except RegexSafetyError as exc:
            issues.append(ValidationIssue(f"{path}.pattern", exc.code, str(exc)))
        target = _extractor_target(extractor)
        if target is not None:
            message = _validate_variable_name(target)
            if message:
                issues.append(ValidationIssue(f"{path}.name", "invalid_variable_name", message))
            group = extractor.get("group")
            if group is not None and compiled is not None:
                if isinstance(group, bool) or not isinstance(group, (int, str)):
                    issues.append(ValidationIssue(f"{path}.group", "invalid_regex_group", "regex group must be an integer index or named group"))
                elif isinstance(group, int) and (group < 0 or group > compiled.groups):
                    issues.append(ValidationIssue(f"{path}.group", "invalid_regex_group", "regex group index does not exist"))
                elif isinstance(group, str) and group not in compiled.groupindex:
                    issues.append(ValidationIssue(f"{path}.group", "invalid_regex_group", "named regex group does not exist"))
        elif compiled is not None and not compiled.groupindex:
            issues.append(ValidationIssue(path, "missing_regex_targets", "regex extraction without a target requires named groups"))
    elif extractor_type in {"copy_field", "copy_to_variable"}:
        try:
            normalize_field_reference(extractor.get("source"))
        except ValueError as exc:
            issues.append(ValidationIssue(f"{path}.source", "invalid_field_reference", str(exc)))
        message = _validate_variable_name(_extractor_target(extractor))
        if message:
            issues.append(ValidationIssue(f"{path}.name", "invalid_variable_name", message))
    elif extractor_type == "json_path":
        source = extractor.get("source", "raw")
        try:
            normalize_field_reference(source)
        except ValueError as exc:
            issues.append(ValidationIssue(f"{path}.source", "invalid_field_reference", str(exc)))
        message = _validate_json_path(extractor.get("path"))
        if message:
            issues.append(ValidationIssue(f"{path}.path", "invalid_json_path", message))
        message = _validate_variable_name(_extractor_target(extractor))
        if message:
            issues.append(ValidationIssue(f"{path}.name", "invalid_variable_name", message))
    elif extractor_type == "split":
        try:
            normalize_field_reference(extractor.get("source"))
        except ValueError as exc:
            issues.append(ValidationIssue(f"{path}.source", "invalid_field_reference", str(exc)))
        delimiter = extractor.get("delimiter")
        if not isinstance(delimiter, str) or not delimiter:
            issues.append(ValidationIssue(f"{path}.delimiter", "invalid_delimiter", "split delimiter must be a non-empty string"))
        targets = extractor.get("targets")
        target = _extractor_target(extractor)
        if targets is not None:
            if not isinstance(targets, list) or not targets:
                issues.append(ValidationIssue(f"{path}.targets", "invalid_targets", "split targets must be a non-empty list"))
            else:
                if len(targets) > MAX_VARIABLES:
                    issues.append(ValidationIssue(f"{path}.targets", "variable_limit", "split has too many targets"))
                seen_targets = set()
                for index, name in enumerate(targets):
                    message = _validate_variable_name(name)
                    if message:
                        issues.append(ValidationIssue(f"{path}.targets[{index}]", "invalid_variable_name", message))
                    elif name in seen_targets:
                        issues.append(ValidationIssue(f"{path}.targets[{index}]", "duplicate_variable_name", "split targets must be unique"))
                    else:
                        seen_targets.add(name)
        elif target is not None:
            message = _validate_variable_name(target)
            if message:
                issues.append(ValidationIssue(f"{path}.name", "invalid_variable_name", message))
            index = extractor.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                issues.append(ValidationIssue(f"{path}.index", "invalid_split_index", "split index must be a non-negative integer"))
        else:
            issues.append(ValidationIssue(path, "missing_split_target", "split requires name and index, or targets"))
    elif extractor_type in {"set_variable", "static"}:
        message = _validate_variable_name(_extractor_target(extractor))
        if message:
            issues.append(ValidationIssue(f"{path}.name", "invalid_variable_name", message))
        value = extractor.get("value")
        if isinstance(value, str) and ("{{" in value or "}}" in value):
            issues.extend(validate_template(value, path=f"{path}.value"))
    elif extractor_type in {"lowercase", "uppercase", "trim"}:
        source = extractor.get("source")
        try:
            normalize_field_reference(source)
        except ValueError as exc:
            issues.append(ValidationIssue(f"{path}.source", "invalid_field_reference", str(exc)))
        message = _validate_variable_name(_extractor_target(extractor))
        if message:
            issues.append(ValidationIssue(f"{path}.name", "invalid_variable_name", message))
    return issues


def validate_extractors(extractors: Any, *, path: str = "extractors") -> List[ValidationIssue]:
    if not isinstance(extractors, list):
        return [ValidationIssue(path, "invalid_extractors", "extractors must be a list")]
    if len(extractors) > MAX_VARIABLES:
        return [ValidationIssue(path, "extractor_limit", "too many variable extractors")]
    issues: List[ValidationIssue] = []
    for index, extractor in enumerate(extractors):
        issues.extend(validate_extractor(extractor, path=f"{path}[{index}]"))
    return issues


def _parse_json_path(path: str) -> List[Any]:
    """Parse a small, non-executable JSONPath subset.

    Supported forms: ``$``, ``$.a.b``, ``$['a']``, ``$[0]`` and combinations.
    Wildcards, filters, scripts and recursive descent are intentionally absent.
    """

    if not path.startswith("$"):
        raise ExtractionError("JSON path must start with $")
    tokens: List[Any] = []
    index = 1
    while index < len(path):
        if path[index] == ".":
            index += 1
            match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", path[index:])
            if not match:
                raise ExtractionError("invalid dotted JSON path segment")
            tokens.append(match.group(0))
            index += len(match.group(0))
        elif path[index] == "[":
            end = path.find("]", index + 1)
            if end == -1:
                raise ExtractionError("unclosed JSON path bracket")
            raw = path[index + 1 : end].strip()
            if re.fullmatch(r"0|[1-9][0-9]*", raw):
                tokens.append(int(raw))
            elif len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
                try:
                    value = bytes(raw[1:-1], "utf-8").decode("unicode_escape")
                except UnicodeDecodeError as exc:
                    raise ExtractionError("invalid escaped JSON path key") from exc
                if not value:
                    raise ExtractionError("JSON path key cannot be empty")
                tokens.append(value)
            else:
                raise ExtractionError("JSON path brackets only support integer indexes or quoted keys")
            index = end + 1
        else:
            raise ExtractionError("invalid JSON path syntax")
    return tokens


def _json_path_get(value: Any, path: str) -> Any:
    current = value
    for token in _parse_json_path(path):
        if isinstance(token, int):
            if not isinstance(current, Sequence) or isinstance(current, (str, bytes, bytearray)):
                raise ExtractionError("JSON path expected a list")
            if token >= len(current):
                raise ExtractionError("JSON path index does not exist")
            current = current[token]
        else:
            if not isinstance(current, Mapping) or token not in current:
                raise ExtractionError("JSON path key does not exist")
            current = current[token]
    return current


def _bounded_value(value: Any) -> Any:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ExtractionError("extracted variable must be JSON-compatible") from exc
    if len(encoded) > MAX_VARIABLE_VALUE_LENGTH:
        raise ExtractionError("extracted variable exceeds the value size limit")
    return copy.deepcopy(value)


def _set_variable(variables: MutableMapping[str, Any], name: str, value: Any) -> None:
    if name not in variables and len(variables) >= MAX_VARIABLES:
        raise ExtractionError("variable count exceeds the limit")
    variables[name] = _bounded_value(value)


def _context_with_variables(context: Mapping[str, Any], variables: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(context)
    result["variables"] = dict(variables)
    return result


def extract_variables(
    extractors: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
    *,
    initial_variables: Optional[Mapping[str, Any]] = None,
) -> ExtractionResult:
    issues = validate_extractors(list(extractors))
    if issues:
        first = issues[0]
        raise ExtractionError(first.message, path=first.path)

    variables: Dict[str, Any] = {}
    initial = dict(initial_variables or context.get("variables") or {})
    if len(initial) > MAX_VARIABLES:
        raise ExtractionError("initial variable count exceeds the limit")
    for name, value in initial.items():
        message = _validate_variable_name(name)
        if message:
            raise ExtractionError(message, path=f"variables.{name}")
        _set_variable(variables, name, value)
    steps: List[ExtractionStepResult] = []
    outcome = "continue"

    for index, extractor in enumerate(extractors):
        extractor_type = extractor["type"]
        failure_mode = extractor.get("on_failure", "continue")
        produced: Dict[str, Any] = {}
        try:
            current_context = _context_with_variables(context, variables)
            if extractor_type == "extract_regex":
                resolution = resolve_field(current_context, extractor["source"])
                if not resolution.found:
                    raise ExtractionError("regex source field does not exist")
                match = compile_safe_regex(extractor["pattern"]).search(
                    bounded_regex_input(resolution.value)
                )
                if match is None:
                    raise ExtractionError("regex did not match")
                target = _extractor_target(extractor)
                if target is not None:
                    group = extractor.get("group", 1 if match.lastindex else 0)
                    try:
                        produced[target] = match.group(group)
                    except (IndexError, KeyError) as exc:
                        raise ExtractionError("requested regex group does not exist") from exc
                else:
                    produced.update(match.groupdict())
                    if not produced:
                        raise ExtractionError("regex extraction requires a target or named groups")
            elif extractor_type in {"copy_field", "copy_to_variable"}:
                resolution = resolve_field(current_context, extractor["source"])
                if not resolution.found:
                    raise ExtractionError("copy source field does not exist")
                produced[_extractor_target(extractor)] = resolution.value
            elif extractor_type == "json_path":
                resolution = resolve_field(current_context, extractor.get("source", "raw"))
                if not resolution.found:
                    raise ExtractionError("JSON path source field does not exist")
                produced[_extractor_target(extractor)] = _json_path_get(
                    resolution.value, extractor["path"]
                )
            elif extractor_type == "split":
                resolution = resolve_field(current_context, extractor["source"])
                if not resolution.found:
                    raise ExtractionError("split source field does not exist")
                if not isinstance(resolution.value, str):
                    raise ExtractionError("split source must be a string")
                parts = resolution.value.split(extractor["delimiter"], MAX_SPLIT_PARTS)
                if len(parts) > MAX_SPLIT_PARTS:
                    raise ExtractionError("split produced too many parts")
                targets = extractor.get("targets")
                if targets is not None:
                    if len(parts) < len(targets):
                        raise ExtractionError("split produced fewer parts than targets")
                    produced.update(zip(targets, parts))
                else:
                    split_index = extractor["index"]
                    if split_index >= len(parts):
                        raise ExtractionError("split index does not exist")
                    produced[_extractor_target(extractor)] = parts[split_index]
            elif extractor_type in {"set_variable", "static"}:
                value = extractor.get("value")
                if isinstance(value, str) and ("{{" in value or "}}" in value):
                    value = render_template(value, current_context).value
                produced[_extractor_target(extractor)] = value
            elif extractor_type in {"lowercase", "uppercase", "trim"}:
                resolution = resolve_field(current_context, extractor["source"])
                if not resolution.found:
                    raise ExtractionError("transform source field does not exist")
                if not isinstance(resolution.value, str):
                    raise ExtractionError("transform source must be a string")
                if extractor_type == "lowercase":
                    value = resolution.value.lower()
                elif extractor_type == "uppercase":
                    value = resolution.value.upper()
                else:
                    value = resolution.value.strip()
                produced[_extractor_target(extractor)] = value

            for name, value in produced.items():
                _set_variable(variables, name, value)
            steps.append(
                ExtractionStepResult(index, extractor_type, True, "extraction_succeeded", "variables extracted", dict(produced), failure_mode)
            )
        except (ExtractionError, RegexSafetyError, ValueError) as exc:
            steps.append(
                ExtractionStepResult(index, extractor_type, False, getattr(exc, "code", "variable_extraction_failed"), str(exc), {}, failure_mode)
            )
            if failure_mode in {"stop_rule", "stop_orchestration"}:
                outcome = failure_mode
                break

    return ExtractionResult(dict(variables), tuple(steps), outcome)
