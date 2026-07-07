from math import prod

IMPACT_STATUSES = {
    "operational",
    "degraded",
    "partial_outage",
    "major_outage",
    "maintenance",
    "disabled",
    "unknown",
}

STATUS_RANK = {
    "disabled": -1,
    "operational": 0,
    "unknown": 0,
    "maintenance": 1,
    "degraded": 2,
    "partial_outage": 3,
    "major_outage": 4,
}

STATUS_IMPACT_SCORE = {
    "disabled": 0,
    "operational": 0,
    "maintenance": 20,
    "unknown": 20,
    "degraded": 40,
    "partial_outage": 65,
    "major_outage": 100,
}

PRIORITY_IMPACT_SCORE = {
    "p0": 100,
    "p1": 100,
    "p2": 75,
    "p3": 45,
    "p4": 20,
    "p5": 5,
}

PRIORITY_ORDER_SCORE = {
    0: 100,
    1: 100,
    2: 75,
    3: 45,
    4: 20,
    5: 5,
}

SEVERITY_RANK = {
    None: 0,
    "": 0,
    "none": 0,
    "info": 1,
    "informational": 1,
    "low": 1,
    "minor": 1,
    "warning": 2,
    "warn": 2,
    "medium": 2,
    "error": 3,
    "high": 3,
    "critical": 4,
    "fatal": 4,
    "page": 4,
}

SEVERITY_IMPACT_SCORE = {
    None: 0,
    "": 0,
    "none": 0,
    "info": 5,
    "informational": 5,
    "low": 15,
    "minor": 15,
    "warning": 40,
    "warn": 40,
    "medium": 35,
    "error": 65,
    "high": 65,
    "critical": 80,
    "fatal": 100,
    "page": 80,
}

DEPENDENCY_IMPACT_MULTIPLIER = {
    ("hard", "required"): 1.0,
    ("hard", "critical"): 1.0,
    ("hard", "important"): 0.85,
    ("hard", "optional"): 0.65,
    ("soft", "required"): 0.75,
    ("soft", "critical"): 0.75,
    ("soft", "important"): 0.55,
    ("soft", "optional"): 0.30,
    ("external", "required"): 0.60,
    ("external", "critical"): 0.60,
    ("external", "important"): 0.40,
    ("external", "optional"): 0.20,
    ("informational", "required"): 0.0,
    ("informational", "critical"): 0.0,
    ("informational", "important"): 0.0,
    ("informational", "optional"): 0.0,
    ("informational", "informational"): 0.0,
}

COMPONENT_CRITICALITY_MULTIPLIER = {
    "required": 1.0,
    "critical": 1.0,
    "important": 0.75,
    "optional": 0.40,
    "informational": 0.0,
}


def clamp_impact_score(score) -> int:
    try:
        score = int(round(float(score or 0)))
    except (TypeError, ValueError):
        score = 0

    return max(0, min(100, score))


def normalize_status(status) -> str:
    status = str(status or "unknown").strip().lower()

    if status not in IMPACT_STATUSES:
        return "unknown"

    return status


def normalize_severity(severity) -> str | None:
    severity = str(severity or "").strip().lower()

    if not severity:
        return None

    if severity == "warn":
        return "warning"

    return severity


def status_rank(status) -> int:
    return STATUS_RANK.get(normalize_status(status), 0)


def status_impact_score(status) -> int:
    return STATUS_IMPACT_SCORE.get(normalize_status(status), 20)


def status_from_impact_score(score, *, unknown=False, maintenance=False, disabled=False) -> str:
    score = clamp_impact_score(score)

    if disabled:
        return "disabled"

    if maintenance and score <= STATUS_IMPACT_SCORE["maintenance"]:
        return "maintenance"

    if unknown and score < 25:
        return "unknown"

    if score >= 80:
        return "major_outage"

    if score >= 55:
        return "partial_outage"

    if score >= 25:
        return "degraded"

    return "operational"


def max_status(*statuses) -> str:
    normalized = [normalize_status(status) for status in statuses]
    return max(normalized, key=status_rank)


def max_severity(left, right):
    left = normalize_severity(left)
    right = normalize_severity(right)

    if SEVERITY_RANK.get(right, 0) > SEVERITY_RANK.get(left, 0):
        return right

    return left


def priority_slug_for_alert_group(group) -> str | None:
    priority = getattr(group, "priority", None)

    if priority and getattr(priority, "slug", None):
        return str(priority.slug).strip().lower()

    slug = getattr(group, "priority_slug", None)

    if slug:
        return str(slug).strip().lower()

    return None


def alert_group_has_explicit_priority(group) -> bool:
    if getattr(group, "priority_id", None):
        return True

    if bool(getattr(group, "priority_set_manually", False)):
        return True

    slug = priority_slug_for_alert_group(group)
    order = getattr(group, "priority_order", None)

    if slug and slug != "p3":
        return True

    try:
        if order is not None and int(order) != 3:
            return True
    except (TypeError, ValueError):
        pass

    return False


def priority_impact_score(group) -> int | None:
    slug = priority_slug_for_alert_group(group)

    if slug in PRIORITY_IMPACT_SCORE:
        return PRIORITY_IMPACT_SCORE[slug]

    try:
        order = int(getattr(group, "priority_order", 0) or 0)
    except (TypeError, ValueError):
        order = 0

    if order in PRIORITY_ORDER_SCORE:
        return PRIORITY_ORDER_SCORE[order]

    return None


def severity_impact_score(severity) -> int:
    severity = normalize_severity(severity)
    return SEVERITY_IMPACT_SCORE.get(severity, 0)


def alert_group_impact_score(group) -> tuple[int, str]:
    """Return impact score and source for one open alert group."""
    if alert_group_has_explicit_priority(group):
        priority_score = priority_impact_score(group)

        if priority_score is not None:
            return clamp_impact_score(priority_score), "priority"

    return clamp_impact_score(severity_impact_score(getattr(group, "severity", None))), "severity"


def dependency_impact_multiplier(dependency) -> float:
    dependency_type = str(getattr(dependency, "dependency_type", None) or "hard").strip().lower()
    criticality = str(getattr(dependency, "criticality", None) or "important").strip().lower()

    if dependency_type == "informational" or criticality == "informational":
        return 0.0

    if (dependency_type, criticality) in DEPENDENCY_IMPACT_MULTIPLIER:
        return DEPENDENCY_IMPACT_MULTIPLIER[(dependency_type, criticality)]

    if dependency_type == "hard":
        return 0.85

    if dependency_type == "soft":
        return 0.55

    if dependency_type == "external":
        return 0.40

    return 0.0


def propagate_dependency_impact(dependency, upstream_status, upstream_score):
    """Return propagated dependency impact details."""
    upstream_status = normalize_status(upstream_status)

    if upstream_status in {"operational", "maintenance", "disabled"}:
        return {
            "status": "operational",
            "score": 0,
            "multiplier": 0.0,
        }

    multiplier = dependency_impact_multiplier(dependency)

    if multiplier <= 0:
        return {
            "status": "operational",
            "score": 0,
            "multiplier": multiplier,
        }

    upstream_score = max(status_impact_score(upstream_status), clamp_impact_score(upstream_score))
    score = clamp_impact_score(upstream_score * multiplier)
    status = status_from_impact_score(score, unknown=(upstream_status == "unknown"))

    return {
        "status": status,
        "score": score,
        "multiplier": multiplier,
    }


def combined_impact_score(scores) -> int:
    """Combine independent component scores without exceeding 100."""
    values = [clamp_impact_score(score) / 100 for score in scores if clamp_impact_score(score) > 0]

    if not values:
        return 0

    return clamp_impact_score(100 * (1 - prod(1 - value for value in values)))
