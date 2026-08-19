
from peewee import fn

from app.modules.db.models import (
    AlertRoute,
    MatcherPreset,
    NotificationPolicyRule,
    PriorityPolicyRule,
    Service,
    ServiceMatchRule,
    Silence,
    ServiceRunbook,
)
from app.modules.common import utc_now


def count_service_runbook_usages(preset_id):
    """Return number of active service runbooks on active services using a preset."""
    return (
        ServiceRunbook
        .select(ServiceRunbook.id)
        .join(Service)
        .where(
            ServiceRunbook.matcher_preset == preset_id,
            ServiceRunbook.deleted == False,
            Service.deleted == False,
        )
        .count()
    )


def count_silence_usages(preset_id):
    """Return number of active silences using a preset."""
    return (
        Silence.select(Silence.id)
        .where(
            Silence.matcher_preset == preset_id,
            Silence.deleted == False,
        )
        .count()
    )


def count_route_usages(preset_id):
    """Return number of active routes using a preset."""
    return (
        AlertRoute.select(AlertRoute.id)
        .where(
            AlertRoute.matcher_preset == preset_id,
            AlertRoute.deleted == False,
        )
        .count()
    )


def count_service_match_rule_usages(preset_id):
    """Return number of active service match rules on active services using a preset."""
    return (
        ServiceMatchRule
        .select(ServiceMatchRule.id)
        .join(Service)
        .where(
            ServiceMatchRule.matcher_preset == preset_id,
            ServiceMatchRule.deleted == False,
            Service.deleted == False,
        )
        .count()
    )


def list_matcher_presets(
    *,
    team_id=None,
    team_ids=None,
    enabled_only=False,
    include_deleted=False,
):
    """Return matcher presets ordered by team and name."""
    query = MatcherPreset.select()

    if not include_deleted:
        query = query.where(MatcherPreset.deleted == False)

    if team_id is not None:
        query = query.where(MatcherPreset.team == team_id)

    if team_ids is not None:
        team_ids = list(team_ids)

        if not team_ids:
            return []

        query = query.where(MatcherPreset.team.in_(team_ids))

    if enabled_only:
        query = query.where(MatcherPreset.enabled == True)

    return list(
        query.order_by(
            MatcherPreset.name.asc(),
            MatcherPreset.id.asc(),
        )
    )


def get_matcher_preset(preset_id, include_deleted=False):
    """Return one matcher preset."""
    query = MatcherPreset.select().where(MatcherPreset.id == preset_id)

    if not include_deleted:
        query = query.where(MatcherPreset.deleted == False)

    return query.get()


def get_matcher_preset_or_none(preset_id, include_deleted=False):
    """Return one matcher preset or None."""
    if not preset_id:
        return None

    query = MatcherPreset.select().where(MatcherPreset.id == preset_id)

    if not include_deleted:
        query = query.where(MatcherPreset.deleted == False)

    return query.first()


def get_matcher_preset_by_team_and_name(
    team_id,
    name,
    *,
    include_deleted=False,
    exclude_preset_id=None,
):
    """Return preset by case-insensitive name inside one team."""
    query = MatcherPreset.select().where(
        MatcherPreset.team == team_id,
        fn.LOWER(MatcherPreset.name) == name.lower(),
    )

    if not include_deleted:
        query = query.where(MatcherPreset.deleted == False)

    if exclude_preset_id is not None:
        query = query.where(MatcherPreset.id != exclude_preset_id)

    return query.first()


def create_matcher_preset(
    *,
    team_id,
    name,
    description=None,
    matchers=None,
    enabled=True,
):
    """Create a matcher preset."""
    return MatcherPreset.create(
        team=team_id,
        name=name,
        description=description,
        matchers=matchers or {},
        enabled=enabled,
        version=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def restore_matcher_preset(
    preset_id,
    *,
    name,
    description=None,
    matchers=None,
    enabled=True,
):
    """Restore a soft-deleted matcher preset."""
    preset = get_matcher_preset(preset_id, include_deleted=True)

    preset.name = name
    preset.description = description
    preset.matchers = matchers or {}
    preset.enabled = enabled
    preset.version = int(preset.version or 0) + 1
    preset.deleted = False
    preset.deleted_at = None
    preset.updated_at = utc_now()
    preset.save()

    return preset


def update_matcher_preset(preset_id, data):
    """Update a matcher preset."""
    preset = get_matcher_preset(preset_id)

    allowed_fields = {
        "name",
        "description",
        "matchers",
        "enabled",
        "version",
    }

    for field, value in data.items():
        if field in allowed_fields:
            setattr(preset, field, value)

    preset.updated_at = utc_now()
    preset.save()

    return preset


def count_notification_policy_usages(preset_id):
    """Return number of active notification rules using a preset."""
    return (
        NotificationPolicyRule.select(NotificationPolicyRule.id)
        .where(
            NotificationPolicyRule.matcher_preset == preset_id,
            NotificationPolicyRule.deleted == False,
        )
        .count()
    )


def count_priority_policy_usages(preset_id):
    """Return number of active priority rules using a preset."""
    return (
        PriorityPolicyRule.select(PriorityPolicyRule.id)
        .where(
            PriorityPolicyRule.matcher_preset == preset_id,
            PriorityPolicyRule.deleted == False,
        )
        .count()
    )


def count_matcher_preset_usages(preset_id):
    """Return total number of active resources using a preset."""
    return (
            count_notification_policy_usages(preset_id)
            + count_priority_policy_usages(preset_id)
            + count_route_usages(preset_id)
            + count_service_match_rule_usages(preset_id)
            + count_silence_usages(preset_id)
            + count_service_runbook_usages(preset_id)
    )


def list_matcher_preset_usages(preset_id):
    """Return active rules using a preset."""
    service_runbooks = list(
        ServiceRunbook
        .select(ServiceRunbook, Service)
        .join(Service)
        .where(
            ServiceRunbook.matcher_preset == preset_id,
            ServiceRunbook.deleted == False,
            Service.deleted == False,
        )
    )
    silences = list(
        Silence.select().where(
            Silence.matcher_preset == preset_id,
            Silence.deleted == False,
        )
    )

    notification_rules = list(
        NotificationPolicyRule.select().where(
            NotificationPolicyRule.matcher_preset == preset_id,
            NotificationPolicyRule.deleted == False,
        )
    )

    priority_rules = list(
        PriorityPolicyRule.select().where(
            PriorityPolicyRule.matcher_preset == preset_id,
            PriorityPolicyRule.deleted == False,
        )
    )

    routes = list(
        AlertRoute.select().where(
            AlertRoute.matcher_preset == preset_id,
            AlertRoute.deleted == False,
        )
    )

    service_match_rules = list(
        ServiceMatchRule
        .select(ServiceMatchRule, Service)
        .join(Service)
        .where(
            ServiceMatchRule.matcher_preset == preset_id,
            ServiceMatchRule.deleted == False,
            Service.deleted == False,
        )
    )

    return {
        "notification_policy_rules": notification_rules,
        "priority_policy_rules": priority_rules,
        "routes": routes,
        "service_match_rules": service_match_rules,
        "silences": silences,
        "service_runbooks": service_runbooks,
    }


def soft_delete_matcher_preset(preset_id):
    """Soft-delete a matcher preset."""
    preset = get_matcher_preset(preset_id)
    now = utc_now()

    preset.enabled = False
    preset.deleted = True
    preset.deleted_at = now
    preset.updated_at = now
    preset.save()

    return preset
