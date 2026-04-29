from datetime import datetime

from app.models import AlertRoute, NotificationChannel, Rotation, Silence, Team, TeamUser


def list_teams(active_only=False, group_ids=None, include_deleted=False):
    """
    Return teams ordered by id.
    """

    query = Team.select().order_by(Team.id.asc())

    if not include_deleted:
        query = query.where(Team.deleted == False)

    if group_ids is not None:
        if not group_ids:
            return []
        query = query.where(Team.group.in_(group_ids))

    if active_only:
        query = query.where(Team.active == True)

    return list(query)


def get_team(team_id, include_deleted=False):
    """
    Return a team by id.
    """

    query = Team.select().where(Team.id == team_id)

    if not include_deleted:
        query = query.where(Team.deleted == False)

    return query.get()


def get_team_by_slug(slug):
    """
    Return a team by slug.
    """

    return Team.get_or_none(
        (Team.slug == slug)
        & (Team.deleted == False)
    )


def create_team(slug, name, description=None, escalation_enabled=True, escalation_after_reminders=2, group_id=None):
    """
    Create a team.
    """

    return Team.create(
        group=group_id,
        slug=slug,
        name=name,
        description=description,
        escalation_enabled=escalation_enabled,
        escalation_after_reminders=escalation_after_reminders,
    )


def create_team_if_missing(slug, name, description=None, escalation_enabled=True, escalation_after_reminders=2, group_id=None):
    """
    Create a team if it does not exist.
    """

    team, _ = Team.get_or_create(
        slug=slug,
        defaults={
            "name": name,
            "group": group_id,
            "description": description,
            "escalation_enabled": escalation_enabled,
            "escalation_after_reminders": escalation_after_reminders,
        },
    )

    if team.deleted:
        team.deleted = False
        team.deleted_at = None
        team.active = True
        team.save()

    return team


def update_team(team_id, data):
    """
    Update a team.
    """

    team = get_team(team_id)

    for field in ["group", "slug", "name", "description", "escalation_enabled", "escalation_after_reminders", "active"]:
        if field in data:
            setattr(team, field, data[field])

    team.save()
    return team


def list_team_users(team_id):
    """
    Return users assigned to a team.
    """

    return list(
        TeamUser.select()
        .where(TeamUser.team == team_id)
        .order_by(TeamUser.id.asc())
    )


def add_user_to_team(team_id, user_id, role="read_only"):
    """
    Add a user to a team.
    """

    membership, created = TeamUser.get_or_create(
        team=team_id,
        user=user_id,
        defaults={"role": role},
    )

    if not created:
        membership.role = role
        membership.active = True
        membership.save()

    return membership


def disable_team(team_id):
    """
    Soft-delete a team and disable its resources.
    """

    return soft_delete_team(team_id)


def soft_delete_team(team_id):
    """
    Soft-delete a team and disable all resources under it.
    """

    now = datetime.utcnow()

    team = get_team(team_id)
    team.active = False
    team.deleted = True
    team.deleted_at = now
    team.save()

    Rotation.update(
        deleted=True,
        deleted_at=now,
        enabled=False,
    ).where(
        (Rotation.team == team.id)
        & (Rotation.deleted == False)
    ).execute()

    AlertRoute.update(
        deleted=True,
        deleted_at=now,
        enabled=False,
    ).where(
        (AlertRoute.team == team.id)
        & (AlertRoute.deleted == False)
    ).execute()

    NotificationChannel.update(
        deleted=True,
        deleted_at=now,
        enabled=False,
    ).where(
        (NotificationChannel.team == team.id)
        & (NotificationChannel.deleted == False)
    ).execute()

    Silence.update(
        deleted=True,
        deleted_at=now,
        enabled=False,
    ).where(
        (Silence.team == team.id)
        & (Silence.deleted == False)
    ).execute()

    return team


def get_team_membership(membership_id):
    """
    Return a team membership by id.
    """

    return TeamUser.get_by_id(membership_id)


def update_team_membership(membership_id, role, active=True):
    """
    Update a team membership.
    """

    membership = get_team_membership(membership_id)
    membership.role = role
    membership.active = active
    membership.save()
    return membership


def disable_team_membership(membership_id):
    """
    Disable a team membership.
    """

    membership = get_team_membership(membership_id)
    membership.active = False
    membership.save()
    return membership
