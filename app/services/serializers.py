def serialize_group(group):
    """
    Serialize a group.
    """

    return {
        "id": group.id,
        "slug": group.slug,
        "name": group.name,
        "description": group.description,
        "active": group.active,
    }


def serialize_user_group(membership):
    """
    Serialize a group membership.
    """

    return {
        "id": membership.id,
        "group_id": membership.group.id,
        "group_slug": membership.group.slug,
        "group_name": membership.group.name,
        "role": membership.role,
        "active": membership.active,
    }


def serialize_team(team):
    """
    Serialize a team.
    """

    return {
        "id": team.id,
        "group_id": team.group.id if team.group else None,
        "group_slug": team.group.slug if team.group else None,
        "group_name": team.group.name if team.group else None,
        "slug": team.slug,
        "name": team.name,
        "description": team.description,
        "escalation_enabled": team.escalation_enabled,
        "escalation_after_reminders": team.escalation_after_reminders,
        "active": team.active,
    }


def serialize_user(user, groups=None):
    """
    Serialize a user.
    """

    data = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "telegram_chat_id": user.telegram_chat_id,
        "slack_user_id": user.slack_user_id,
        "mattermost_user_id": user.mattermost_user_id,
        "active": user.active,
        "is_admin": user.is_admin,
        "active_group_id": user.active_group.id if user.active_group else None,
        "active_group_slug": user.active_group.slug if user.active_group else None,
    }

    if groups is not None:
        data["groups"] = [serialize_user_group(item) for item in groups]

    return data


def serialize_user_short(user):
    """
    Serialize a compact user object.
    """

    if not user:
        return None

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "telegram_chat_id": user.telegram_chat_id,
        "slack_user_id": user.slack_user_id,
        "mattermost_user_id": user.mattermost_user_id,
    }


def serialize_rotation(rotation, current_user=None):
    """
    Serialize a rotation.
    """

    return {
        "id": rotation.id,
        "team_id": rotation.team.id,
        "team_slug": rotation.team.slug,
        "name": rotation.name,
        "description": rotation.description,
        "start_at": rotation.start_at.isoformat(),
        "duration_seconds": rotation.duration_seconds,
        "reminder_interval_seconds": rotation.reminder_interval_seconds,
        "rotation_type": rotation.rotation_type,
        "interval_value": rotation.interval_value,
        "interval_unit": rotation.interval_unit,
        "handoff_time": rotation.handoff_time,
        "handoff_weekday": rotation.handoff_weekday,
        "timezone": rotation.timezone,
        "enabled": rotation.enabled,
        "current_oncall": current_user.username if current_user else None,
    }


def serialize_channel(channel):
    """
    Serialize a notification channel.
    """

    return {
        "id": channel.id,
        "group_id": channel.group.id if getattr(channel, "group", None) else None,
        "group_slug": channel.group.slug if getattr(channel, "group", None) else None,
        "team_id": channel.team.id if channel.team else None,
        "team_slug": channel.team.slug if channel.team else None,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "config": channel.config,
        "enabled": channel.enabled,
    }


def serialize_channel_short(channel):
    """
    Serialize a compact channel object.
    """

    if not channel:
        return None

    return {
        "id": channel.id,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "enabled": channel.enabled,
    }


def serialize_route(route):
    """
    Serialize an alert route.
    """

    channels = [serialize_channel_short(link.channel) for link in route.route_channels]
    return {
        "id": route.id,
        "team_id": route.team.id,
        "team_slug": route.team.slug,
        "name": route.name,
        "source": route.source,
        "rotation_id": route.rotation.id if route.rotation else None,
        "rotation_name": route.rotation.name if route.rotation else None,
        "matchers": route.matchers,
        "group_by": route.group_by,
        "enabled": route.enabled,
        "intake_token_prefix": route.intake_token_prefix,
        "has_intake_token": bool(route.intake_token_hash),
        "channels": channels,
    }


def serialize_alert_event(event):
    """
    Serialize an alert event.
    """

    return {
        "id": event.id,
        "event_type": event.event_type,
        "message": event.message,
        "user": serialize_user_short(event.user),
        "created_at": event.created_at.isoformat(),
    }


def serialize_alert_notification(notification):
    """
    Serialize an alert notification delivery record.
    """

    return {
        "id": notification.id,
        "channel": serialize_channel_short(notification.channel),
        "provider": notification.provider,
        "external_message_id": notification.external_message_id,
        "external_channel_id": notification.external_channel_id,
        "last_event_type": notification.last_event_type,
        "last_error": notification.last_error,
        "created_at": notification.created_at.isoformat(),
        "updated_at": notification.updated_at.isoformat(),
    }


def serialize_alert(alert, include_payload=False, include_details=False, events=None, notifications=None):
    """
    Serialize an alert.
    """

    team = alert.team
    route = alert.route
    rotation = alert.rotation

    data = {
        "id": alert.id,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "route_id": route.id if route else None,
        "route_name": route.name if route else None,
        "route_source": route.source if route else None,
        "rotation_id": rotation.id if rotation else None,
        "rotation_name": rotation.name if rotation else None,
        "rotation_reminder_interval_seconds": rotation.reminder_interval_seconds if rotation else None,
        "source": alert.source,
        "external_id": alert.external_id,
        "dedup_key": alert.dedup_key,
        "group_key": alert.group_key,
        "title": alert.title,
        "message": alert.message,
        "severity": alert.severity,
        "status": alert.status,
        "previous_status": alert.previous_status,
        "silenced": alert.silenced,
        "labels": alert.labels or {},
        "labels_count": len(alert.labels or {}),
        "assignee": alert.assignee.username if alert.assignee else None,
        "assignee_id": alert.assignee.id if alert.assignee else None,
        "assignee_details": serialize_user_short(alert.assignee),
        "acknowledged_by": alert.acknowledged_by.username if alert.acknowledged_by else None,
        "acknowledged_by_details": serialize_user_short(alert.acknowledged_by),
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "first_seen_at": alert.first_seen_at.isoformat(),
        "last_seen_at": alert.last_seen_at.isoformat(),
        "last_notification_at": alert.last_notification_at.isoformat() if alert.last_notification_at else None,
        "reminder_count": alert.reminder_count,
        "escalation_level": alert.escalation_level,
    }

    if route:
        data["route"] = {
            "id": route.id,
            "name": route.name,
            "source": route.source,
            "matchers": route.matchers,
            "group_by": route.group_by,
            "enabled": route.enabled,
        }

    if rotation:
        data["rotation"] = {
            "id": rotation.id,
            "name": rotation.name,
            "duration_seconds": rotation.duration_seconds,
            "reminder_interval_seconds": rotation.reminder_interval_seconds,
            "rotation_type": rotation.rotation_type,
            "interval_value": rotation.interval_value,
            "interval_unit": rotation.interval_unit,
            "handoff_time": rotation.handoff_time,
            "timezone": rotation.timezone,
            "enabled": rotation.enabled,
        }

    if include_payload:
        data["payload"] = alert.payload

    if include_details:
        data["events"] = [serialize_alert_event(event) for event in events or []]
        data["notifications"] = [serialize_alert_notification(item) for item in notifications or []]

    return data
