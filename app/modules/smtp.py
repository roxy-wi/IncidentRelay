"""Shared SMTP transport for all IncidentRelay email delivery paths.

Every email IncidentRelay sends goes through the globally configured
``[smtp]`` server. This module owns the connect / STARTTLS / AUTH / send
sequence so that the alert email channel, stakeholder notifications and
incident participant notifications cannot drift apart in how they
validate configuration or report transport errors.
"""

import smtplib
from email.message import EmailMessage

from app.settings import Config

SMTP_TIMEOUT_SECONDS = 10

MISSING_HOST_ERROR = "smtp host is missing: set [smtp] host in config"
PARTIAL_AUTH_ERROR = (
    "SMTP auth is partially configured: both [smtp] user and password "
    "must be set, or both must be empty"
)
AUTH_UNSUPPORTED_ERROR = (
    "SMTP auth is configured, but the SMTP server does not support AUTH. "
    "Clear [smtp] user/password for an unauthenticated relay, or use an "
    "SMTP server that supports AUTH."
)


def build_plain_message(recipient, subject, body):
    """Build a plain-text email message addressed to one recipient."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = Config.SMTP_FROM
    message["To"] = recipient
    message.set_content(body)

    return message


def send_email_message(message):
    """Send a prepared email message through the configured SMTP server.

    Raises RuntimeError when SMTP is not configured, when authentication is
    only partially configured, or when credentials are supplied to a server
    that does not advertise AUTH.
    """
    smtp_host = Config.SMTP_HOST

    if not smtp_host:
        raise RuntimeError(MISSING_HOST_ERROR)

    smtp_port = int(Config.SMTP_PORT)

    username = (Config.SMTP_USER or "").strip()
    password = Config.SMTP_PASSWORD or ""

    with smtplib.SMTP(
        smtp_host,
        smtp_port,
        timeout=SMTP_TIMEOUT_SECONDS,
    ) as smtp:
        smtp.ehlo()

        if Config.SMTP_USE_TLS:
            smtp.starttls()
            smtp.ehlo()

        if username or password:
            if not username or not password:
                raise RuntimeError(PARTIAL_AUTH_ERROR)

            if not smtp.has_extn("auth"):
                raise RuntimeError(AUTH_UNSUPPORTED_ERROR)

            smtp.login(username, password)

        smtp.send_message(message)


def send_plain_email(recipient, subject, body):
    """Build and send a plain-text email to one recipient."""
    send_email_message(build_plain_message(recipient, subject, body))
