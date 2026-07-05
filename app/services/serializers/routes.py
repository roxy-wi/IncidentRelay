from app.services.serializers.channels import serialize_channel_short
from app.services.serializers.common import attach_team_permissions
from app.services.serializers.services import serialize_active_maintenance_for_scope


def serialize_route_integration_config(route):
    """Serialize provider-specific integration config without secrets."""
    config = route.integration_config or {}

    if route.source == "sentry":
        sentry = dict(
            config.get("sentry") or {}
        )

        return {
            "sentry": {
                "has_webhook_secret": bool(
                    sentry.get("webhook_secret")
                ),
                "webhook_path": (
                    f"/api/integrations/sentry/{route.id}"
                ),
                "base_url": sentry.get("base_url"),
                "organization_slug": sentry.get("organization_slug"),
            }
        }

    if route.source == "aws_sns":
        aws_sns = dict(
            config.get("aws_sns") or {}
        )

        return {
            "aws_sns": {
                "topic_arn": aws_sns.get(
                    "topic_arn"
                ),
                "webhook_path": (
                    f"/api/integrations/aws-sns/{route.id}"
                ),
            }
        }

    return {}


def serialize_route(route, current_user=None):
    """
    Serialize an alert route.
    """

    channels = [serialize_channel_short(link.channel) for link in route.route_channels]
    matcher_preset = (
        route.matcher_preset
        if getattr(route, "matcher_preset_id", None)
        else None
    )

    data = {
        "id": route.id,
        "team_id": route.team.id,
        "team_name": route.team.name,
        "team_slug": route.team.slug,
        "name": route.name,
        "source": route.source,
        "rotation_id": route.rotation.id if route.rotation else None,
        "rotation_name": route.rotation.name if route.rotation else None,
        "escalation_policy_id": route.escalation_policy.id if route.escalation_policy else None,
        "escalation_policy_name": route.escalation_policy.name if route.escalation_policy else None,
        "escalation_mode": "policy" if route.escalation_policy else "rotation",
        "team_escalation_enabled": route.team.escalation_enabled if route.team else None,
        "team_escalation_after_reminders": (
            route.team.escalation_after_reminders if route.team else None
        ),
        "matcher_preset_id": matcher_preset.id if matcher_preset else None,
        "matcher_preset": {
            "id": matcher_preset.id,
            "name": matcher_preset.name,
            "version": matcher_preset.version,
            "enabled": matcher_preset.enabled,
        } if matcher_preset else None,
        "matchers": route.matchers,
        "group_by": route.group_by,
        "integration_config": serialize_route_integration_config(route),
        "notification_channel_mode": route.notification_channel_mode or "route_only",
        "enabled": route.enabled,
        "intake_token_prefix": route.intake_token_prefix,
        "has_intake_token": bool(route.intake_token_hash),
        "channels": channels,
        "service_id": route.service.id if getattr(route, "service_id", None) else None,
        "service_name": route.service.name if getattr(route, "service_id", None) else None,
        "service_slug": route.service.slug if getattr(route, "service_id", None) else None,
        "active_maintenance": serialize_active_maintenance_for_scope(
            group_id=route.team.group_id if route.team_id and route.team else None,
            team_id=route.team_id,
            service_id=route.service_id,
            route_id=route.id,
        ),
    }

    data = attach_team_permissions(data, route.team.id, current_user)

    if current_user and route.team_id:
        from app.services.rbac import can_access_team_or_group_resource

        data.setdefault("permissions", {})["can_write"] = (
            can_access_team_or_group_resource(
                current_user,
                route.team_id,
                write_required=True,
            )
        )

    return data
