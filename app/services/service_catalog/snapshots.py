def service_owner_snapshot(owner):
    user = owner.user if getattr(owner, "user_id", None) else None

    return {
        "id": owner.id,
        "user_id": owner.user_id,
        "user_display_name": (
            user.display_name or user.username or user.email
            if user
            else None
        ),
        "user_email": user.email if user else None,
        "role": owner.role,
        "active": owner.active,
        "notify_on_created": bool(owner.notify_on_created),
        "notify_on_priority_change": bool(owner.notify_on_priority_change),
        "notify_on_status_change": bool(owner.notify_on_status_change),
        "notify_on_resolved": bool(owner.notify_on_resolved),
        "notify_on_comment": bool(owner.notify_on_comment),
    }



def service_link_snapshot(link):
    return {
        "id": link.id,
        "service_id": link.service_id,
        "link_type": link.link_type,
        "label": link.label,
        "url": link.url,
        "description": link.description,
        "priority": link.priority,
        "enabled": link.enabled,
    }



def service_runbook_snapshot(runbook):
    matcher_preset = (
        runbook.matcher_preset
        if getattr(runbook, "matcher_preset_id", None)
        else None
    )

    return {
        "id": runbook.id,
        "service_id": runbook.service_id,
        "title": runbook.title,
        "description": runbook.description,
        "url": runbook.url,
        "severity": runbook.severity,
        "matcher_preset_id": runbook.matcher_preset_id,
        "matcher_preset_name": matcher_preset.name if matcher_preset else None,
        "matchers": runbook.matchers or {},
        "priority": runbook.priority,
        "enabled": runbook.enabled,
    }



def service_dependency_snapshot(dependency):
    service = dependency.service if getattr(dependency, "service_id", None) else None
    depends_on = (
        dependency.depends_on_service
        if getattr(dependency, "depends_on_service_id", None)
        else None
    )

    return {
        "id": dependency.id,
        "service_id": dependency.service_id,
        "service_name": service.name if service else None,
        "service_slug": service.slug if service else None,
        "depends_on_service_id": dependency.depends_on_service_id,
        "depends_on_service_name": depends_on.name if depends_on else None,
        "depends_on_service_slug": depends_on.slug if depends_on else None,
        "dependency_type": dependency.dependency_type,
        "criticality": dependency.criticality,
        "correlation_enabled": dependency.correlation_enabled,
        "propagation_delay_seconds": dependency.propagation_delay_seconds,
        "description": dependency.description,
        "metadata": dependency.metadata or {},
        "enabled": dependency.enabled,
    }



def service_match_rule_snapshot(rule):
    route = rule.route if getattr(rule, "route_id", None) else None
    preset = (
        rule.matcher_preset
        if getattr(rule, "matcher_preset_id", None)
        else None
    )

    return {
        "id": rule.id,
        "team_id": rule.team_id,
        "route_id": rule.route_id,
        "route_name": route.name if route else None,
        "service_id": rule.service_id,
        "position": rule.position,
        "name": rule.name,
        "description": rule.description,
        "matcher_preset_id": rule.matcher_preset_id,
        "matcher_preset_name": preset.name if preset else None,
        "matchers": rule.matchers or {},
        "enabled": rule.enabled,
    }


def service_standard_snapshot(standard):
    return {
        "id": standard.id,
        "group_id": standard.group_id,
        "slug": standard.slug,
        "name": standard.name,
        "description": standard.description,
        "applies_to": standard.applies_to or {},
        "enabled": standard.enabled,
        "deleted": standard.deleted,
    }


def service_standard_check_snapshot(check):
    return {
        "id": check.id,
        "standard_id": check.standard_id,
        "slug": check.slug,
        "name": check.name,
        "description": check.description,
        "check_type": check.check_type,
        "configuration": check.configuration or {},
        "weight": check.weight,
        "severity": check.severity,
        "required": check.required,
        "enabled": check.enabled,
        "deleted": check.deleted,
        "position": check.position,
    }


def service_slo_snapshot(slo):
    return {
        "id": slo.id,
        "service_id": slo.service_id,
        "name": slo.name,
        "description": slo.description,
        "severity": slo.severity,
        "ack_target_seconds": slo.ack_target_seconds,
        "resolve_target_seconds": slo.resolve_target_seconds,
        "availability_target_basis_points": slo.availability_target_basis_points,
        "enabled": slo.enabled,
        "deleted": slo.deleted,
    }
