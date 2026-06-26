import re

NAME_MIN_LENGTH = 2
NAME_MAX_LENGTH = 40

TOKEN_NAME_MIN_LENGTH = 1
TOKEN_NAME_MAX_LENGTH = 40

USERNAME_MIN_LENGTH = 2
USERNAME_MAX_LENGTH = 40

SLUG_MIN_LENGTH = 1
SLUG_MAX_LENGTH = 40

DISPLAY_NAME_MAX_LENGTH = 40
DESCRIPTION_MAX_LENGTH = 120
CONTACT_ID_MAX_LENGTH = 40
ROLE_MAX_LENGTH = 32

PHONE_MIN_DIGITS = 5
PHONE_MAX_DIGITS = 20
PHONE_MAX_LENGTH = PHONE_MAX_DIGITS + 1
PHONE_RE = re.compile(rf"^\+?[0-9]{{{PHONE_MIN_DIGITS},{PHONE_MAX_DIGITS}}}$")
PHONE_FORMAT_ALLOWED_RE = re.compile(r"^[0-9+\s().-]+$")


def normalize_phone(value):
    """
    Normalize user phone number.

    Accepted input examples:
    - +7 (111) 111-11-11
    - +7-111-111-11-11
    - +7 111 111 11 11
    - 71111111111

    Stored output:
    - +71111111111
    - 71111111111
    """
    if value is None:
        return None

    value = str(value).strip()
    if not value:
        return None

    if not PHONE_FORMAT_ALLOWED_RE.fullmatch(value):
        raise ValueError(
            "phone may contain digits, spaces, parentheses, dots, hyphens "
            "and one optional leading +"
        )

    plus_count = value.count("+")

    if plus_count > 1:
        raise ValueError("phone may contain only one +")

    if plus_count == 1 and not value.startswith("+"):
        raise ValueError("phone + must be at the beginning")

    has_plus = value.startswith("+")
    digits = re.sub(r"\D", "", value)

    normalized = ("+" if has_plus else "") + digits

    if not PHONE_RE.fullmatch(normalized):
        raise ValueError(
            "phone must contain "
            f"{PHONE_MIN_DIGITS}-{PHONE_MAX_DIGITS} digits "
            "and optionally one leading +"
        )

    return normalized
