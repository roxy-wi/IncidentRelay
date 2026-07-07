from __future__ import annotations


def _split_query_value(value):
    """Split one query-string value into normalized non-empty strings."""
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_split_query_value(item))
        return result

    return [
        item.strip()
        for item in str(value).split(",")
        if item is not None and item.strip()
    ]


def get_multi_query_values(args, name, aliases=None):
    """
    Return query-string values for repeated and comma-separated filters.

    Supported forms for name="status":
    - ?status=firing&status=acknowledged
    - ?status=firing,acknowledged
    - ?statuses=firing,acknowledged when aliases=["statuses"]
    """
    aliases = aliases or []
    raw_values = []

    for key in [name, *aliases]:
        raw_values.extend(args.getlist(key))

    values = []
    seen = set()

    for value in _split_query_value(raw_values):
        if value in seen:
            continue

        seen.add(value)
        values.append(value)

    return values
