"""Calendar feed repository."""


from app.modules.db.models import CalendarFeed
from app.modules.common import utc_now


def list_calendar_feeds(team_id):
    return (
        CalendarFeed
        .select()
        .where(
            CalendarFeed.team == team_id,
            CalendarFeed.deleted == False,  # noqa: E712
        )
        .order_by(CalendarFeed.created_at.desc())
    )


def get_calendar_feed(feed_id):
    return CalendarFeed.get(
        CalendarFeed.id == feed_id,
        CalendarFeed.deleted == False,  # noqa: E712
    )


def get_calendar_feed_by_prefix(token_prefix):
    return CalendarFeed.get(
        CalendarFeed.token_prefix == token_prefix,
        CalendarFeed.deleted == False,  # noqa: E712
    )


def create_calendar_feed(
    *,
    team_id,
    name,
    token_prefix,
    token_hash,
    created_by=None,
    past_days=7,
    future_days=90,
):
    return CalendarFeed.create(
        team=team_id,
        name=name or "On-call calendar",
        token_prefix=token_prefix,
        token_hash=token_hash,
        created_by=created_by,
        past_days=past_days,
        future_days=future_days,
        enabled=True,
    )


def update_calendar_feed(feed, **fields):
    for key, value in fields.items():
        setattr(feed, key, value)

    feed.save()
    return feed


def mark_calendar_feed_used(feed):
    feed.last_used_at = utc_now()
    feed.save(only=[CalendarFeed.last_used_at])


def soft_delete_calendar_feed(feed):
    feed.deleted = True
    feed.deleted_at = utc_now()
    feed.enabled = False
    feed.save(
        only=[
            CalendarFeed.deleted,
            CalendarFeed.deleted_at,
            CalendarFeed.enabled,
        ]
    )
