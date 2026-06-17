def object_display_name(obj, fallback):
    if not obj:
        return fallback

    return (
        getattr(obj, "display_name", None)
        or getattr(obj, "name", None)
        or getattr(obj, "username", None)
        or getattr(obj, "slug", None)
        or getattr(obj, "email", None)
        or fallback
    )


def user_display_name(user):
    if not user:
        return "Someone"

    return object_display_name(
        user,
        f"user #{user.id}",
    )


def responder_target_label(responder):
    """Return human readable responder target label."""
    if responder.target_type == "user":
        return object_display_name(
            responder.target_user if responder.target_user_id else None,
            f"User #{responder.target_user_id}",
        )

    if responder.target_type == "team":
        return object_display_name(
            responder.target_team if responder.target_team_id else None,
            f"Team #{responder.target_team_id}",
        )

    if responder.target_type == "rotation":
        return object_display_name(
            responder.target_rotation if responder.target_rotation_id else None,
            f"Rotation #{responder.target_rotation_id}",
        )

    if responder.target_type == "escalation_policy":
        return object_display_name(
            (
                responder.target_escalation_policy
                if responder.target_escalation_policy_id
                else None
            ),
            f"Escalation policy #{responder.target_escalation_policy_id}",
        )

    return "Responder"
