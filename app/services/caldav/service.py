from datetime import timedelta

from app.modules.db.models import Team, TeamUser
from app.services.calendar_service import build_team_calendar
from app.services.caldav.ics import event_uid
from app.modules.common import utc_now

DEFAULT_PAST_DAYS = 7
DEFAULT_FUTURE_DAYS = 90


def list_user_calendar_teams(user):
    query = (
        Team
        .select()
        .join(TeamUser)
        .where(
            TeamUser.user == user,
            TeamUser.active == True,  # noqa: E712
            Team.active == True,  # noqa: E712
            Team.deleted == False,  # noqa: E712
        )
        .order_by(Team.name)
    )

    return list(query)


def get_user_team_or_none(user, team_id):
    try:
        team = Team.get(
            Team.id == team_id,
            Team.active == True,  # noqa: E712
            Team.deleted == False,  # noqa: E712
        )
    except Team.DoesNotExist:
        return None

    exists = (
        TeamUser
        .select()
        .where(
            TeamUser.team == team,
            TeamUser.user == user,
            TeamUser.active == True,  # noqa: E712
        )
        .exists()
    )

    if not exists:
        return None

    return team


def list_team_caldav_events(team):
    now = utc_now()
    start_at = now - timedelta(days=DEFAULT_PAST_DAYS)
    end_at = now + timedelta(days=DEFAULT_FUTURE_DAYS)

    events = build_team_calendar(team.id, start_at, end_at)

    for event in events:
        event["team_id"] = team.id
        event.setdefault("team_name", team.name)
        event.setdefault("team_slug", team.slug)

    return events


def find_event_by_uid(team, uid):
    for event in list_team_caldav_events(team):
        if event_uid(event) == uid:
            return event

    return None
