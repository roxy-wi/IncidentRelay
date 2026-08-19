
from app.modules.db.models import ServiceStandard, ServiceStandardCheck
from app.modules.common import utc_now


APPLICABILITY_FIELDS = {
    "kinds": "kind",
    "lifecycles": "lifecycle",
    "environments": "environment",
    "tiers": "tier",
    "criticalities": "criticality",
    "service_types": "service_type",
}

APPLICABILITY_VALUES = {
    "kinds": {"technical", "business", "component"},
    "lifecycles": {
        "experimental",
        "development",
        "production",
        "deprecated",
        "retired",
    },
    "environments": {
        "production",
        "staging",
        "development",
        "testing",
        "shared",
    },
    "tiers": {"tier_1", "tier_2", "tier_3", "tier_4"},
    "criticalities": {"low", "medium", "high", "critical"},
    "service_types": {
        "api",
        "web",
        "database",
        "queue",
        "cache",
        "worker",
        "cron",
        "network",
        "storage",
        "infrastructure",
        "external",
        "other",
    },
}

CHECK_CONFIGURATION_FIELDS = {
    "field_present": {"field"},
    "field_equals": {"field", "value"},
    "owner_exists": {"roles", "minimum"},
    "active_rotation_exists": set(),
    "escalation_policy_exists": {"require_rules"},
    "notification_policy_exists": {"require_rules", "require_channels"},
    "service_channel_exists": {"purposes", "minimum"},
    "route_exists": set(),
    "match_rule_exists": {"minimum"},
    "runbook_exists": {"minimum", "severities"},
    "link_type_exists": {"link_type", "link_types", "minimum"},
    "dependency_exists": {
        "minimum",
        "dependency_types",
        "criticalities",
        "correlation_enabled",
    },
    "dependency_cycle_absent": {"correlation_only"},
    "metadata_value": {"key", "value"},
}

CHECK_REQUIRED_CONFIGURATION_FIELDS = {
    "field_present": {"field"},
    "field_equals": {"field", "value"},
    "metadata_value": {"key"},
}

CHECK_LIST_CONFIGURATION_FIELDS = {
    "roles",
    "purposes",
    "severities",
    "link_types",
    "dependency_types",
    "criticalities",
}

CHECK_BOOLEAN_CONFIGURATION_FIELDS = {
    "require_rules",
    "require_channels",
    "correlation_enabled",
    "correlation_only",
}

CHECK_MINIMUM_CONFIGURATION_FIELDS = {"minimum"}

CHECK_SEVERITIES = {"info", "warning", "critical"}

OWNER_ROLES = {
    "owner",
    "stakeholder",
    "business_owner",
    "executive",
    "support",
    "customer_success",
    "custom",
}

SERVICE_CHANNEL_PURPOSES = {
    "notification",
    "stakeholder",
    "status",
    "escalation",
}

RUNBOOK_SEVERITIES = {
    "critical",
    "high",
    "warning",
    "info",
    "unknown",
}

LINK_TYPES = {
    "dashboard",
    "metrics",
    "logs",
    "traces",
    "repository",
    "documentation",
    "status_page",
    "wiki",
    "other",
}

DEPENDENCY_TYPES = {
    "hard",
    "soft",
    "external",
    "informational",
}

DEPENDENCY_CRITICALITIES = {
    "required",
    "important",
    "optional",
}


class ServiceStandardValidationError(ValueError):
    pass


def get_service_group_id(service):
    if service.group_id:
        return service.group_id

    if service.team_id and service.team:
        return service.team.group_id

    return None


def standard_applies_to_service(standard, service):
    rules = standard.applies_to or {}

    for rule_name, service_field in APPLICABILITY_FIELDS.items():
        accepted_values = rules.get(rule_name) or []

        if accepted_values and getattr(service, service_field, None) not in accepted_values:
            return False

    expected_labels = rules.get("labels") or {}
    service_labels = service.labels or {}

    if not isinstance(service_labels, dict):
        service_labels = {}

    for key, expected_value in expected_labels.items():
        actual_value = service_labels.get(key)

        if isinstance(expected_value, list):
            if actual_value not in expected_value:
                return False
        elif actual_value != expected_value:
            return False

    return True


def list_applicable_standards(service):
    group_id = get_service_group_id(service)

    if group_id is None:
        return []

    standards = ServiceStandard.select().where(
        ServiceStandard.group == group_id,
        ServiceStandard.enabled == True,
        ServiceStandard.deleted == False,
    )

    return [
        standard
        for standard in standards.order_by(
            ServiceStandard.name,
            ServiceStandard.id,
        )
        if standard_applies_to_service(standard, service)
    ]


def validate_standard_applies_to(applies_to):
    applies_to = applies_to or {}

    if not isinstance(applies_to, dict):
        raise ServiceStandardValidationError(
            "Standard applies_to must be an object"
        )

    allowed_fields = set(APPLICABILITY_FIELDS) | {"labels"}
    unknown_fields = set(applies_to) - allowed_fields

    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise ServiceStandardValidationError(
            f"Unsupported applies_to fields: {fields}"
        )

    normalized: dict[str, object] = {}

    for field, allowed_values in APPLICABILITY_VALUES.items():
        values = applies_to.get(field)

        if values is None:
            continue

        if not isinstance(values, list):
            raise ServiceStandardValidationError(
                f'applies_to field "{field}" must be a list'
            )

        invalid_values = set(values) - allowed_values

        if invalid_values:
            invalid = ", ".join(sorted(str(value) for value in invalid_values))
            raise ServiceStandardValidationError(
                f'Unsupported values for applies_to field "{field}": {invalid}'
            )

        normalized[field] = list(dict.fromkeys(values))

    labels = applies_to.get("labels")

    if labels is not None:
        if not isinstance(labels, dict):
            raise ServiceStandardValidationError(
                'applies_to field "labels" must be an object'
            )

        for key, value in labels.items():
            if not isinstance(key, str) or not key.strip():
                raise ServiceStandardValidationError(
                    "Standard label keys must be non-empty strings"
                )

            if isinstance(value, list) and not value:
                raise ServiceStandardValidationError(
                    f'Label matcher "{key}" cannot contain an empty list'
                )

        normalized["labels"] = labels

    return normalized


def validate_standard_check(check_type, configuration):
    if check_type not in CHECK_CONFIGURATION_FIELDS:
        raise ServiceStandardValidationError(
            f'Unsupported readiness check type "{check_type}"'
        )

    configuration = configuration or {}

    if not isinstance(configuration, dict):
        raise ServiceStandardValidationError(
            "Readiness check configuration must be an object"
        )

    allowed_fields = CHECK_CONFIGURATION_FIELDS[check_type]
    unknown_fields = set(configuration) - allowed_fields

    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise ServiceStandardValidationError(
            f'Unsupported configuration fields for "{check_type}": {fields}'
        )

    required_fields = CHECK_REQUIRED_CONFIGURATION_FIELDS.get(
        check_type,
        set(),
    )
    missing_fields = required_fields - set(configuration)

    if missing_fields:
        fields = ", ".join(sorted(missing_fields))
        raise ServiceStandardValidationError(
            f'Missing configuration fields for "{check_type}": {fields}'
        )

    for field in CHECK_LIST_CONFIGURATION_FIELDS & set(configuration):
        value = configuration[field]

        if not isinstance(value, list):
            raise ServiceStandardValidationError(
                f'Check configuration field "{field}" must be a list'
            )

    for field in CHECK_BOOLEAN_CONFIGURATION_FIELDS & set(configuration):
        value = configuration[field]

        if not isinstance(value, bool):
            raise ServiceStandardValidationError(
                f'Check configuration field "{field}" must be a boolean'
            )

    for field in CHECK_MINIMUM_CONFIGURATION_FIELDS & set(configuration):
        value = configuration[field]

        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ServiceStandardValidationError(
                f'Check configuration field "{field}" must be an integer greater than zero'
            )

    if check_type in {"field_present", "field_equals"}:
        _validate_non_empty_string(configuration.get("field"), "field")

    if check_type == "metadata_value":
        _validate_non_empty_string(configuration.get("key"), "key")

    if check_type == "owner_exists":
        _validate_allowed_list(
            configuration.get("roles"),
            OWNER_ROLES,
            "roles",
        )

    if check_type == "service_channel_exists":
        _validate_allowed_list(
            configuration.get("purposes"),
            SERVICE_CHANNEL_PURPOSES,
            "purposes",
        )

    if check_type == "runbook_exists":
        _validate_allowed_list(
            configuration.get("severities"),
            RUNBOOK_SEVERITIES,
            "severities",
        )

    if check_type == "link_type_exists":
        link_type = configuration.get("link_type")
        link_types = configuration.get("link_types")

        if link_type is not None and link_types is not None:
            raise ServiceStandardValidationError(
                'Use either "link_type" or "link_types", not both'
            )

        if link_type is not None:
            _validate_allowed_value(link_type, LINK_TYPES, "link_type")

        _validate_allowed_list(link_types, LINK_TYPES, "link_types")

    if check_type == "dependency_exists":
        _validate_allowed_list(
            configuration.get("dependency_types"),
            DEPENDENCY_TYPES,
            "dependency_types",
        )
        _validate_allowed_list(
            configuration.get("criticalities"),
            DEPENDENCY_CRITICALITIES,
            "criticalities",
        )

    return dict(configuration)


def list_service_standards(group_ids, include_disabled=False):
    if not group_ids:
        return []

    query = ServiceStandard.select().where(
        ServiceStandard.group.in_(group_ids),
        ServiceStandard.deleted == False,
    )

    if not include_disabled:
        query = query.where(ServiceStandard.enabled == True)

    return list(
        query.order_by(
            ServiceStandard.group,
            ServiceStandard.name,
            ServiceStandard.id,
        )
    )


def get_service_standard(standard_id):
    return ServiceStandard.get(
        ServiceStandard.id == standard_id,
        ServiceStandard.deleted == False,
    )


def create_service_standard(data, actor_user=None):
    values = dict(data)
    values["applies_to"] = validate_standard_applies_to(
        values.get("applies_to")
    )
    values["created_by"] = actor_user.id if actor_user else None
    values["created_at"] = utc_now()
    values["updated_at"] = utc_now()

    return ServiceStandard.create(**values)


def update_service_standard(standard, data):
    values = dict(data)

    if "applies_to" in values:
        values["applies_to"] = validate_standard_applies_to(
            values["applies_to"]
        )

    for field, value in values.items():
        setattr(standard, field, value)

    standard.updated_at = utc_now()
    standard.save()

    return standard


def delete_service_standard(standard):
    database = ServiceStandard._meta.database
    now = utc_now()

    with database.atomic():
        ServiceStandardCheck.update(
            deleted=True,
            enabled=False,
            updated_at=now,
        ).where(
            ServiceStandardCheck.standard == standard.id,
            ServiceStandardCheck.deleted == False,
        ).execute()

        standard.deleted = True
        standard.enabled = False
        standard.updated_at = now
        standard.save()

    return standard


def list_standard_checks(standard_id, include_disabled=False):
    query = ServiceStandardCheck.select().where(
        ServiceStandardCheck.standard == standard_id,
        ServiceStandardCheck.deleted == False,
    )

    if not include_disabled:
        query = query.where(ServiceStandardCheck.enabled == True)

    return list(
        query.order_by(
            ServiceStandardCheck.position,
            ServiceStandardCheck.id,
        )
    )


def get_standard_check(standard_id, check_id):
    return ServiceStandardCheck.get(
        ServiceStandardCheck.id == check_id,
        ServiceStandardCheck.standard == standard_id,
        ServiceStandardCheck.deleted == False,
    )


def create_standard_check(standard, data):
    values = dict(data)
    values["configuration"] = validate_standard_check(
        values["check_type"],
        values.get("configuration"),
    )
    values["standard"] = standard.id
    values["created_at"] = utc_now()
    values["updated_at"] = utc_now()

    return ServiceStandardCheck.create(**values)


def update_standard_check(check, data):
    values = dict(data)
    check_type = values.get("check_type", check.check_type)
    configuration = values.get("configuration", check.configuration)

    values["configuration"] = validate_standard_check(
        check_type,
        configuration,
    )

    for field, value in values.items():
        setattr(check, field, value)

    check.updated_at = utc_now()
    check.save()

    return check


def delete_standard_check(check):
    check.deleted = True
    check.enabled = False
    check.updated_at = utc_now()
    check.save()

    return check


def _validate_non_empty_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ServiceStandardValidationError(
            f'Check configuration field "{field}" must be a non-empty string'
        )


def _validate_allowed_value(value, allowed_values, field):
    if value not in allowed_values:
        raise ServiceStandardValidationError(
            f'Unsupported value for check configuration field "{field}": {value}'
        )


def _validate_allowed_list(values, allowed_values, field):
    if values is None:
        return

    invalid_values = set(values) - allowed_values

    if invalid_values:
        invalid = ", ".join(sorted(str(value) for value in invalid_values))
        raise ServiceStandardValidationError(
            f'Unsupported values for check configuration field "{field}": {invalid}'
        )
