from dataclasses import dataclass, field

from app.modules.db import incidents_repo, priority_policies_repo
from app.services.incidents.priority_policies import service as policy_service
from app.services.incidents.priority_policies.constants import (
    FALLBACK_FIXED_PRIORITY,
    SOURCE_PRIORITY_PREFER,
    UPDATE_MODE_RAISE_ONLY,
)
from app.services.routing.matcher.match_context import alert_rule_matches


@dataclass
class PriorityResolution:
    """Resolved priority and information explaining the decision."""

    priority: object
    source: str
    update_mode: str = UPDATE_MODE_RAISE_ONLY
    policy_id: int | None = None
    policy_source: str | None = None
    rule_id: int | None = None
    source_priority_value: object = None
    notes: list[str] = field(default_factory=list)
    rule_errors: list[dict] = field(default_factory=list)

    def to_dict(self):
        priority = self.priority

        return {
            "priority_id": priority.id if priority else None,
            "policy_source": self.policy_source,
            "priority_slug": priority.slug if priority else None,
            "priority_level": priority.level if priority else None,
            "source": self.source,
            "update_mode": self.update_mode,
            "policy_id": self.policy_id,
            "rule_id": self.rule_id,
            "source_priority_value": self.source_priority_value,
            "notes": self.notes,
            "rule_errors": self.rule_errors,
        }


def _source_priority_value(alert_data):
    """Return an explicit priority value supplied by the alert source."""
    labels = alert_data.get("labels") or {}
    payload = alert_data.get("payload") or {}

    candidates = [
        alert_data.get("priority"),
        alert_data.get("priority_slug"),
    ]

    if isinstance(labels, dict):
        candidates.extend([
            labels.get("priority"),
            labels.get("incident_priority"),
        ])

    if isinstance(payload, dict):
        candidates.extend([
            payload.get("priority"),
            payload.get("priority_slug"),
        ])

    for value in candidates:
        if value not in (None, ""):
            return value

    return None


def _priority_from_source_value(value):
    """Resolve an enabled IncidentPriority from an external value."""
    if value in (None, ""):
        return None

    if hasattr(value, "slug"):
        value = value.slug

    if isinstance(value, dict):
        if value.get("id") is not None:
            value = value["id"]
        else:
            value = value.get("slug") or value.get("name")

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return priority_policies_repo.get_incident_priority_or_none(value)

    value = str(value).strip().lower()

    if not value:
        return None

    if value.isdigit():
        return priority_policies_repo.get_incident_priority_or_none(int(value))

    return incidents_repo.get_priority_by_slug(value)


def _severity_fallback(alert_data):
    return incidents_repo.priority_from_severity(alert_data.get("severity"))


def _fixed_fallback_priority(policy):
    priority = policy.fallback_priority

    if not priority or not priority.enabled:
        return None

    return priority


def resolve_incident_priority(
    alert_data,
    *,
    team,
    route=None,
    service=None,
):
    """Resolve automatic incident priority for an incoming alert."""
    team_id = team.id if team else None

    explicit_source_value = _source_priority_value(alert_data)
    explicit_priority_requested = (
        alert_data.get("priority_set_manually")
        or alert_data.get("priority_set_by_orchestration")
    )
    if explicit_priority_requested and explicit_source_value:
        explicit_priority = _priority_from_source_value(explicit_source_value)
        if explicit_priority:
            return PriorityResolution(
                priority=explicit_priority,
                source=(
                    "orchestration"
                    if alert_data.get("priority_set_by_orchestration")
                    else "explicit_source_priority"
                ),
                source_priority_value=explicit_source_value,
            )

    orchestration_policy_id = alert_data.get("orchestration_priority_policy_id")
    if orchestration_policy_id:
        policy = priority_policies_repo.get_priority_policy_or_none(
            orchestration_policy_id
        )
        if policy and (not policy.enabled or policy.team_id != team_id):
            policy = None
    else:
        policy = policy_service.get_effective_policy(
            team_id=team_id,
            service=service,
        )

    if not policy:
        return PriorityResolution(
            priority=_severity_fallback(alert_data),
            source="severity_mapping",
            update_mode="raise_only",
        )

    policy_source = "orchestration" if orchestration_policy_id else "team_default"

    if (
        not orchestration_policy_id
        and service
        and getattr(service, "priority_policy_id", None) == policy.id
    ):
        policy_source = "service"

    update_mode = getattr(policy, "update_mode", None) or "raise_only"

    result = PriorityResolution(
        priority=None,
        source="unresolved",
        update_mode=update_mode,
        policy_id=policy.id,
        policy_source=policy_source,
    )

    source_value = _source_priority_value(alert_data)
    result.source_priority_value = source_value

    if policy.source_priority_mode == SOURCE_PRIORITY_PREFER and source_value:
        source_priority = _priority_from_source_value(source_value)

        if source_priority:
            result.priority = source_priority
            result.source = "source_priority"
            return result

        result.notes.append("invalid_source_priority")

    rules = priority_policies_repo.list_priority_policy_rules(
        policy.id,
        enabled_only=True,
    )

    for rule in rules:
        priority = rule.priority

        if not priority or not priority.enabled:
            result.notes.append(
                f"rule_{rule.id}_priority_disabled"
            )
            continue

        try:
            matched = alert_rule_matches(
                alert_data,
                rule,
                team=team,
                route=route,
                service=service,
            )
        except Exception as exc:
            result.rule_errors.append({
                "rule_id": rule.id,
                "error": str(exc),
            })
            continue

        if not matched:
            continue

        result.priority = priority
        result.source = "policy_rule"
        result.rule_id = rule.id
        return result

    if policy.fallback_mode == FALLBACK_FIXED_PRIORITY:
        fallback_priority = _fixed_fallback_priority(policy)

        if fallback_priority:
            result.priority = fallback_priority
            result.source = "fixed_fallback"
            return result

        result.notes.append("fixed_fallback_priority_missing_or_disabled")

    result.priority = _severity_fallback(alert_data)
    result.source = "severity_mapping"

    return result
