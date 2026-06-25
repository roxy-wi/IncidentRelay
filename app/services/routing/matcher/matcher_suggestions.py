from collections import Counter, defaultdict

from app.modules.db.models import Alert


DEFAULT_SAMPLE_LIMIT = 200
MAX_SAMPLE_LIMIT = 500
DEFAULT_VALUES_LIMIT = 20
MAX_VALUES_LIMIT = 50
MAX_VALUE_LENGTH = 200


def _normalize_value(value):
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None

    value = str(value).strip()

    if not value or len(value) > MAX_VALUE_LENGTH:
        return None

    return value


def _record_value(counters, name, value):
    name = str(name or "").strip()
    value = _normalize_value(value)

    if not name or value is None:
        return

    counters[name][value] += 1


def _serialize_counters(counters, values_limit):
    result = {}

    for name in sorted(counters):
        values = counters[name].most_common(values_limit)
        result[name] = [value for value, _count in values]

    return result


def build_matcher_suggestions(*, team_id, route_id=None, service_id=None, sample_limit=DEFAULT_SAMPLE_LIMIT, values_limit=DEFAULT_VALUES_LIMIT):
    """Collect matcher field and label suggestions from recent alerts."""
    sample_limit = max(1, min(int(sample_limit), MAX_SAMPLE_LIMIT))
    values_limit = max(1, min(int(values_limit), MAX_VALUES_LIMIT))

    query = Alert.select().where(Alert.team == team_id)

    if route_id:
        query = query.where(Alert.route == route_id)

    if service_id:
        query = query.where(Alert.service == service_id)

    alerts = list(query.order_by(Alert.last_seen_at.desc(), Alert.id.desc()).limit(sample_limit))

    label_values = defaultdict(Counter)
    field_values = defaultdict(Counter)

    for alert in alerts:
        for name, value in (alert.labels or {}).items():
            _record_value(label_values, name, value)

        _record_value(label_values, "severity", alert.severity)
        _record_value(label_values, "status", alert.status)
        _record_value(label_values, "source", alert.source)
        _record_value(label_values, "priority", alert.priority_slug)
        _record_value(label_values, "team_id", alert.team_id)
        _record_value(label_values, "route_id", alert.route_id)
        _record_value(label_values, "service_id", alert.service_id)

        _record_value(field_values, "source", alert.source)
        _record_value(field_values, "title", alert.title)
        _record_value(field_values, "severity", alert.severity)
        _record_value(field_values, "status", alert.status)
        _record_value(field_values, "priority", alert.priority_slug)

    return {
        "team_id": team_id,
        "route_id": route_id,
        "service_id": service_id,
        "sample_size": len(alerts),
        "sample_limit": sample_limit,
        "values_limit": values_limit,
        "labels": _serialize_counters(label_values, values_limit),
        "fields": _serialize_counters(field_values, values_limit),
    }
