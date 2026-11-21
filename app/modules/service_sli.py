"""Shared SLI priority rules for validation, evaluation and the web editor."""

import re


PRIORITY_VALUES = ("p1", "p2", "p3", "p4")
PRIORITY_PATTERN = "^(" + "|".join(re.escape(value) for value in PRIORITY_VALUES) + ")$"
IMPACT_SLI_TYPES = ("incident_availability", "incident_count")
DEFAULT_IMPACT_PRIORITY_SCOPE = ("p1", "p2")


def normalize_priority_scope(scope, *, sli_type, priority=None):
    """Resolve defaults and return unique priorities, rejecting invalid scopes.

    Missing impact scopes default to P1/P2. An empty latency scope means all
    priorities; an explicitly empty impact scope is invalid. Unknown values
    raise ValueError instead of silently broadening or narrowing evaluation.
    """
    if scope is None and priority:
        scope = [priority]
    if scope is None and sli_type in IMPACT_SLI_TYPES:
        scope = list(DEFAULT_IMPACT_PRIORITY_SCOPE)
    if isinstance(scope, str):
        scope = [scope]
    if scope is not None and not isinstance(scope, list):
        raise ValueError("priority_scope must be a list")

    normalized = []
    for value in scope or []:
        value = str(value or "").strip().lower()
        if value not in PRIORITY_VALUES:
            raise ValueError(
                "priority_scope values must be one of " + ", ".join(PRIORITY_VALUES)
            )
        if value not in normalized:
            normalized.append(value)

    if sli_type in IMPACT_SLI_TYPES and not normalized:
        raise ValueError("Impact SLI requires priority_scope")
    return normalized
