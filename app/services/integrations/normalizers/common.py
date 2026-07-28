import hashlib
import json
import re


PRIORITY_SEVERITY = {
    "p1": "critical",
    "p2": "high",
    "p3": "medium",
    "p4": "warning",
    "p5": "info",
}


def clean_string(value):
    """Return a stripped string or ``None`` for an empty value."""
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def normalize_event_link(value):
    """Return a clean event/source link value."""
    return clean_string(value)


def first_event_link(*values):
    """Return first non-empty event/source link."""
    for value in values:
        value = normalize_event_link(value)

        if value:
            return value

    return None


def add_event_link_label(labels, event_link):
    """Store external event link in alert labels."""
    event_link = normalize_event_link(event_link)

    if event_link:
        labels.setdefault("event_link", event_link)

    return labels


def make_hash(value):
    """
    Build a stable hash from a Python value.
    """

    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def make_dedup_key(source, external_id=None, title=None, labels=None):
    """
    Create a stable deduplication key.
    """

    return make_hash({"source": source, "external_id": external_id, "title": title, "labels": labels or {}})


def first_non_empty(*values):
    """Return first non-empty string-like value."""
    for value in values:
        if value is None:
            continue

        if isinstance(value, str):
            value = value.strip()

        if value:
            return value

    return None


def first_present(*values):
    """Return the first present value while preserving ``0`` and ``False``."""
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def canonical_label_key(value):
    """Convert an arbitrary label key to lower snake_case."""
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(value or "").strip().lower(),
    ).strip("_")


def normalize_label_value(value):
    """Keep scalar label values and serialize complex values deterministically."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def stable_labels(labels, *, exclude=()):
    """Return deterministically ordered labels without volatile keys."""
    excluded = {str(key) for key in exclude}

    return {
        str(key): labels[key]
        for key in sorted(labels, key=lambda item: str(item))
        if str(key) not in excluded
    }


def severity_from_priority(value):
    """Map a P1-P5 priority to IncidentRelay severity, or return ``None``."""
    priority = clean_string(value)
    if not priority:
        return None

    return PRIORITY_SEVERITY.get(priority.lower())
