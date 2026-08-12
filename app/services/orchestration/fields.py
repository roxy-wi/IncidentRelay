"""Restricted field resolution for orchestration conditions and templates.

The resolver only traverses mappings and sequences. It never performs Python
attribute access, method calls or descriptor evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from .errors import FieldResolutionError, ValidationIssue
from .limits import MAX_FIELD_REFERENCE_LENGTH


ALLOWED_ROOTS = frozenset(
    {
        "event",
        "labels",
        "raw",
        "variables",
        "route",
        "service",
        "team",
        "integration",
        "time",
        "result",
    }
)

# Existing IncidentRelay rules commonly use bare normalized-event fields such
# as "severity". Keep that notation deterministic by resolving it under event.
_BARE_EVENT_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_INDEX = re.compile(r"^(0|[1-9][0-9]*)$")


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


@dataclass(frozen=True)
class FieldResolution:
    reference: str
    found: bool
    value: Any = MISSING
    normalized_reference: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference,
            "normalized_reference": self.normalized_reference,
            "found": self.found,
            "value": None if not self.found else self.value,
        }


def normalize_field_reference(reference: str) -> str:
    if not isinstance(reference, str):
        raise FieldResolutionError("field reference must be a string")
    reference = reference.strip()
    if not reference:
        raise FieldResolutionError("field reference cannot be empty")
    if len(reference) > MAX_FIELD_REFERENCE_LENGTH:
        raise FieldResolutionError("field reference exceeds the size limit")
    if reference.startswith(".") or reference.endswith(".") or ".." in reference:
        raise FieldResolutionError("field reference contains an empty segment")

    parts = reference.split(".")
    if parts[0] not in ALLOWED_ROOTS:
        if len(parts) == 1 and _BARE_EVENT_FIELD.fullmatch(parts[0]):
            parts.insert(0, "event")
        else:
            raise FieldResolutionError(
                "field reference must start with one of: "
                + ", ".join(sorted(ALLOWED_ROOTS))
            )

    for index, part in enumerate(parts):
        if not part:
            raise FieldResolutionError("field reference contains an empty segment")
        if index == 0:
            if part not in ALLOWED_ROOTS:
                raise FieldResolutionError("unsupported field root")
            continue
        if part.startswith("__") and part.endswith("__"):
            raise FieldResolutionError("dunder field path segments are not allowed")
        if not (_SEGMENT.fullmatch(part) or _INDEX.fullmatch(part)):
            raise FieldResolutionError(
                f"invalid field path segment {part!r}; only names and list indexes are allowed"
            )
    return ".".join(parts)


def validate_field_reference(reference: Any, *, path: str = "field") -> Iterable[ValidationIssue]:
    try:
        normalize_field_reference(reference)
    except FieldResolutionError as exc:
        yield ValidationIssue(path, exc.code, str(exc))


def _mapping_get(value: Mapping[str, Any], segment: str) -> Tuple[bool, Any]:
    if segment in value:
        return True, value[segment]
    return False, MISSING


def _sequence_get(value: Sequence[Any], segment: str) -> Tuple[bool, Any]:
    if not _INDEX.fullmatch(segment):
        return False, MISSING
    index = int(segment)
    if index >= len(value):
        return False, MISSING
    return True, value[index]


def resolve_field(context: Mapping[str, Any], reference: str) -> FieldResolution:
    """Resolve a safe dotted reference against an orchestration context."""

    normalized = normalize_field_reference(reference)
    parts = normalized.split(".")
    current: Any = context

    for segment in parts:
        if isinstance(current, Mapping):
            found, current = _mapping_get(current, segment)
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            found, current = _sequence_get(current, segment)
        else:
            found, current = False, MISSING
        if not found:
            return FieldResolution(
                reference=reference,
                normalized_reference=normalized,
                found=False,
            )

    return FieldResolution(
        reference=reference,
        normalized_reference=normalized,
        found=True,
        value=current,
    )


def build_context(
    *,
    event: Mapping[str, Any] | None = None,
    labels: Mapping[str, Any] | None = None,
    raw: Mapping[str, Any] | None = None,
    variables: Mapping[str, Any] | None = None,
    route: Mapping[str, Any] | None = None,
    service: Mapping[str, Any] | None = None,
    team: Mapping[str, Any] | None = None,
    integration: Mapping[str, Any] | None = None,
    time: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a complete evaluator context without mutating caller mappings."""

    event_copy = dict(event or {})
    label_source = labels if labels is not None else event_copy.get("labels")
    labels_copy = dict(label_source or {})
    event_copy["labels"] = labels_copy
    return {
        "event": event_copy,
        "labels": labels_copy,
        "raw": dict(raw or {}),
        "variables": dict(variables or {}),
        "route": dict(route or {}),
        "service": dict(service or {}),
        "team": dict(team or {}),
        "integration": dict(integration or {}),
        "time": dict(time or {}),
        "result": dict(result or {}),
    }
