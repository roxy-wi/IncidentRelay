SEVERITY_ALIASES = {
    "crit": "critical",
    "critical": "critical",
    "error": "critical",
    "fatal": "critical",
    "disaster": "critical",
    "emergency": "critical",

    "high": "high",

    "avg": "medium",
    "average": "medium",
    "medium": "medium",

    "warn": "warning",
    "warning": "warning",

    "low": "low",

    "info": "info",
    "information": "info",
    "informational": "info",
    "not_classified": "info",
    "not classified": "info",
}


def normalize_severity(value):
    """Normalize alert severity names and common integration aliases."""
    normalized = str(value or "").strip().lower()
    return SEVERITY_ALIASES.get(normalized, normalized)


def normalize_severity_list(values):
    """Normalize severity config into a de-duplicated list."""
    if values is None:
        return []

    if isinstance(values, str):
        values = [values]

    if not isinstance(values, list):
        raise ValueError("must be a list of strings")

    result = []
    for item in values:
        severity = normalize_severity(item)
        if severity and severity not in result:
            result.append(severity)

    return result
