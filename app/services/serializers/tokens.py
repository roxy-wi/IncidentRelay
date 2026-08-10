from app.modules.common import utc_now
from app.services.serializers.common import serialize_utc_datetime


def serialize_api_token(token):
    """
    Serialize API token metadata.

    Never expose token_hash or full raw token.
    """
    expires_at = token.expires_at
    expired = bool(expires_at and expires_at <= utc_now())

    return {
        "id": token.id,
        "name": token.name,
        "token_prefix": token.token_prefix,
        "scopes": token.scopes or [],
        "group_id": token.group.id if token.group else None,
        "group_slug": token.group.slug if token.group else None,
        "group_name": token.group.name if token.group else None,
        "team_id": token.team.id if token.team else None,
        "team_slug": token.team.slug if token.team else None,
        "active": token.active,
        "expired": expired,
        "created_at": serialize_utc_datetime(token.created_at),
        "expires_at": serialize_utc_datetime(expires_at),
        "last_used_at": serialize_utc_datetime(token.last_used_at),
    }
