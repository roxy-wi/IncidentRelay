"""Small helpers for service-layer request payloads."""

from typing import Any


def payload_to_dict(payload: Any) -> dict[str, Any]:
    """Return only explicitly supplied fields from a schema or mapping payload."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)

    return dict(payload or {})
