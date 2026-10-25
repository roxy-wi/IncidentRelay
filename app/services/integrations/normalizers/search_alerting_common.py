"""Small pure helpers shared by OpenSearch and Kibana webhook normalizers."""

from collections.abc import Mapping
from urllib.parse import urlsplit

from app.services.integrations.normalizers.common import (
    clean_string,
    make_dedup_key,
    normalize_label_value,
)


RECOVERY_STATES = frozenset({
    "ok", "recovery", "recovered", "resolved", "completed",
    "closed", "inactive", "clear", "cleared",
})


def nested_value(mapping, *keys):
    """Follow a sequence of keys only through dictionaries."""
    for key in keys:
        if not isinstance(mapping, Mapping):
            return None
        mapping = mapping.get(key)
    return mapping


def provider_value(payload, name, *nested_paths):
    """Look for a flat provider key, then its nested equivalents."""
    def scalar(value):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return None
        return clean_string(value)

    value = scalar(payload.get(name))
    if value is not None:
        return value
    for path in nested_paths:
        value = scalar(nested_value(payload, *path))
        if value is not None:
            return value
    return None


def alert_status(*candidates):
    """Only an explicit recovery signal resolves an existing child Alert."""
    for candidate in candidates:
        state = clean_string(candidate)
        if state:
            return "resolved" if state.lower() in RECOVERY_STATES else "firing"
    return "firing"


def sanitized_labels(raw):
    """Retain matcher-friendly labels without nesting provider-owned objects."""
    if not isinstance(raw, Mapping):
        return {}
    labels = {}
    for key, value in raw.items():
        name = clean_string(key)
        if name and value is not None:
            normalized = normalize_label_value(value)
            if normalized is not None:
                labels[name] = normalized
    return labels


def http_event_link(*values):
    """Accept only absolute HTTP(S) source links for outgoing UI links."""
    for candidate in values:
        value = clean_string(candidate)
        if not value:
            continue
        try:
            parts = urlsplit(value)
            if parts.scheme.lower() in {"http", "https"} and parts.hostname:
                return value
        except ValueError:
            # Invalid bracketed IPv6 / malformed URI supplied by a webhook.
            continue
    return None


def stable_search_key(source, components, *, route_id=None, team_slug=None):
    """Hash the stable identity and routing scope, never title/status/message.

    Production supplies route_id from the authenticated intake token. Including
    it prevents a provider with the same monitor/rule IDs on two routes from
    cross-updating a child's lifecycle (find_existing_alert is source-wide).
    """
    scope = (
        f"route:{int(route_id)}" if route_id is not None
        else f"team:{str(team_slug or '').strip()}"
    )
    return make_dedup_key(source, external_id=[scope, *components])
