import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from peewee import DoesNotExist

from app.modules.db import calendar_feeds_repo
from app.services.calendar_service import build_team_calendar
from app.services.caldav.ics import build_calendar_ics


CALENDAR_FEED_TOKEN_PREFIX_LENGTH = 12


def generate_calendar_feed_token():
    token = secrets.token_urlsafe(32)

    return (
        token,
        token[:CALENDAR_FEED_TOKEN_PREFIX_LENGTH],
        hash_calendar_feed_token(token),
    )


def hash_calendar_feed_token(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def verify_calendar_feed_token(feed, token):
    if not feed or not token:
        return False

    return hmac.compare_digest(
        str(feed.token_hash),
        hash_calendar_feed_token(token),
    )


def get_calendar_feed_by_token(token):
    prefix = str(token or "")[:CALENDAR_FEED_TOKEN_PREFIX_LENGTH]

    if not prefix:
        return None

    try:
        feed = calendar_feeds_repo.get_calendar_feed_by_prefix(prefix)
    except DoesNotExist:
        return None

    if not feed.enabled or feed.deleted:
        return None

    if not verify_calendar_feed_token(feed, token):
        return None

    return feed


def build_calendar_feed_url(base_url, token):
    return f"{str(base_url).rstrip('/')}/api/calendar/feeds/{token}.ics"


def serialize_calendar_feed(feed, base_url=None, token=None):
    data = {
        "id": feed.id,
        "team_id": feed.team.id,
        "team_name": feed.team.name,
        "team_slug": feed.team.slug,
        "name": feed.name,
        "enabled": feed.enabled,
        "past_days": feed.past_days,
        "future_days": feed.future_days,
        "created_at": feed.created_at.isoformat() if feed.created_at else None,
        "last_used_at": feed.last_used_at.isoformat() if feed.last_used_at else None,
    }

    if base_url and token:
        data["token"] = token
        data["feed_url"] = build_calendar_feed_url(base_url, token)

    return data


def build_ics_for_calendar_feed(feed):
    now = datetime.utcnow()

    start_at = now - timedelta(days=int(feed.past_days or 7))
    end_at = now + timedelta(days=int(feed.future_days or 90))

    events = build_team_calendar(feed.team.id, start_at, end_at)

    for event in events:
        event.setdefault("team_id", feed.team.id)
        event.setdefault("team_name", feed.team.name)
        event.setdefault("team_slug", feed.team.slug)

    return build_calendar_ics(
        calendar_name=f"IncidentRelay - {feed.team.name} on-call",
        events=events,
    )
