"""Email transport for operational Incident stakeholder updates."""
import smtplib
from email.message import EmailMessage
from app import Config


def send_incident_mail(recipient, subject, body):
    if not recipient:
        return False
    host = Config.SMTP_HOST
    if not host:
        raise RuntimeError("SMTP host is not configured")
    msg = EmailMessage()
    msg["To"] = recipient
    msg["From"] = Config.SMTP_FROM
    msg["Subject"] = subject
    msg.set_content(body)
    username, password = Config.SMTP_USER or "", Config.SMTP_PASSWORD or ""
    with smtplib.SMTP(host, int(Config.SMTP_PORT), timeout=10) as connection:
        connection.ehlo()
        if Config.SMTP_USE_TLS:
            connection.starttls()
            connection.ehlo()
        if username or password:
            if not username or not password:
                raise RuntimeError("SMTP user/password must both be configured")
            connection.login(username, password)
        refused = connection.send_message(msg)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    return True
