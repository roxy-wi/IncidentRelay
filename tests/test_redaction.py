import pytest

from app.modules.redaction import REDACTED, redact_string


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "password=release-secret",
            f"password={REDACTED}",
        ),
        (
            "new secret=do-not-log-this",
            f"new secret={REDACTED}",
        ),
        (
            "token: abc123",
            f"token: {REDACTED}",
        ),
        (
            "password=one&token=two",
            f"password={REDACTED}&token={REDACTED}",
        ),
        (
            'client_secret="quoted secret"',
            f"client_secret={REDACTED}",
        ),
    ],
)
def test_redact_string_hides_inline_secrets(value, expected):
    assert redact_string(value) == expected
