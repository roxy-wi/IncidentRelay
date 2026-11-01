"""Stable user colors shared by profiles, schedules, and collaboration."""


def default_user_color(user_id: int) -> str:
    """Map IDs to distinct RGB colors within the 24-bit color space.

    The odd multiplier permutes all 16,777,216 RGB values, so neighboring
    accounts do not get neighboring shades. Names and memberships do not
    affect the color. No database write or allocation lock is required.
    """
    return f"#{(int(user_id) * 0x9E3779 + 0x5C4B2D) & 0xFFFFFF:06x}"


def user_color(user) -> str | None:
    """Return the saved preference or the account's stable default color."""
    if user is None:
        return None
    return getattr(user, "color", None) or default_user_color(user.id)
