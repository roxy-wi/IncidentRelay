import json
import configparser
from pathlib import Path

from app.config import CONFIG_FILE


class Settings:
    """
    Load service settings from an INI configuration file.
    """

    def __init__(self, path=None):
        """
        Initialize settings from a config file path.
        """
        self.path = Path(path or CONFIG_FILE)
        self.parser = configparser.ConfigParser()
        self.parser.optionxform = str

        if self.path.exists():
            self.parser.read(self.path)

    def get(self, section, option, default=None):
        """
        Return a string setting value.
        """
        if not self.parser.has_section(section):
            return default

        return self.parser.get(section, option, fallback=default)

    def get_int(self, section, option, default=0):
        """
        Return an integer setting value.
        """
        value = self.get(section, option, default)

        if value in (None, ""):
            return default

        return int(value)

    def get_bool(self, section, option, default=False):
        """
        Return a boolean setting value.
        """
        value = self.get(section, option, None)

        if value is None:
            return default

        if isinstance(value, bool):
            return value

        return str(value).strip().lower() in ("1", "true", "yes", "y", "on")

    def get_section(self, section, default=None):
        """Return all options from a config section as a dictionary."""
        if not self.parser.has_section(section):
            return default or {}

        return dict(self.parser.items(section))

    def get_json(self, section, option, default=None):
        """Return a JSON setting value."""
        value = self.get(section, option, None)

        if value in (None, ""):
            return default

        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"invalid JSON setting [{section}] {option}: {exc}"
            ) from exc


settings = Settings()


class Config:
    """
    Flask-compatible settings object built from the external config file.
    """

    SECRET_KEY = settings.get("main", "secret_key", "dev-secret-key")
    DEFAULT_TIMEZONE = settings.get("main", "timezone", "UTC")

    SERVER_HOST = settings.get("server", "host", "0.0.0.0")
    SERVER_PORT = settings.get_int("server", "port", 8080)
    PUBLIC_BASE_URL = settings.get("server", "public_base_url", "http://127.0.0.1:8080")

    DB_TYPE = settings.get("database", "type", "sqlite")
    DB_NAME = settings.get("database", "name", "incidentrelay.db")
    DB_USER = settings.get("database", "user", "")
    DB_PASSWORD = settings.get("database", "password", "")
    DB_HOST = settings.get("database", "host", "127.0.0.1")
    DB_PORT = settings.get_int("database", "port", 0)

    LOG_FILE = settings.get("logging", "file", "./logs/incidentrelay.log")
    LOG_APP_FILE = settings.get(
        "logging",
        "app_file",
        LOG_FILE,
    )
    LOG_SCHEDULER_FILE = settings.get(
        "logging",
        "scheduler_file",
        "./logs/incidentrelay-scheduler.log",
    )
    LOG_TELEGRAM_WORKER_FILE = settings.get(
        "logging",
        "telegram_worker_file",
        "./logs/incidentrelay-telegram-worker.log",
    )
    LOG_LEVEL = settings.get("logging", "level", "INFO")
    LOG_REQUESTS = False

    API_AUTH_REQUIRED = settings.get_bool("auth", "api_auth_required", False)
    RBAC_ENFORCED = settings.get_bool("auth", "rbac_enforced", False)
    JWT_SECRET_KEY = settings.get("auth", "jwt_secret", SECRET_KEY) or SECRET_KEY
    JWT_EXPIRE_MINUTES = settings.get_int("auth", "jwt_expire_minutes", 1440)
    JWT_COOKIE_NAME = settings.get("auth", "jwt_cookie_name", "incidentrelay_jwt")
    JWT_COOKIE_SECURE = settings.get_bool("auth", "jwt_cookie_secure", False)

    SSO_SECRET_ENCRYPTION_KEY = settings.get("sso", "secret_encryption_key", SECRET_KEY)

    REMINDER_INTERVAL_SECONDS = settings.get_int("alerts", "reminder_interval_seconds", 60)
    ALERT_GROUP_WINDOW_SECONDS = settings.get_int("alerts", "alert_group_window_seconds", 3600)

    SCHEDULER_LOCK_TTL_SECONDS = settings.get_int("scheduler", "lock_ttl_seconds", 120)
    USER_NOTIFICATION_RULES_CHECK_INTERVAL_SECONDS = settings.get_int(
        "scheduler",
        "user_notification_rules_check_interval_seconds",
        30,
    )

    MATTERMOST_ACTION_SECRET = settings.get("mattermost", "action_secret", SECRET_KEY)

    SMTP_HOST = settings.get("smtp", "host", "")
    SMTP_PORT = settings.get_int("smtp", "port", 587)
    SMTP_USER = settings.get("smtp", "user", "")
    SMTP_PASSWORD = settings.get("smtp", "password", "")
    SMTP_FROM = settings.get("smtp", "from", "incidentrelay@example.com")
    SMTP_USE_TLS = settings.get_bool("smtp", "use_tls", True)

    VOICE_PROVIDER = settings.get("voice", "provider", "stub")
    VOICE_CALLBACK_SECRET = settings.get("voice", "callback_secret", SECRET_KEY)
    VOICE_TEXT_TEMPLATE = settings.get("voice", "text_template", "")
    VOICE_DTMF_ACTIONS = settings.get_json(
        "voice",
        "dtmf_actions",
        {"1": "acknowledge", "2": "resolve"},
    )
    VOICE_PROVIDER_CONFIG = settings.get_section("voice_provider", {})

    TELEGRAM_PROXY_URL = settings.get("telegram", "proxy_url", "")

    ONCALL_SHIFT_EMAIL_CHECK_INTERVAL_SECONDS = settings.get_int(
        "oncall",
        "shift_email_check_interval_seconds", 60)

    ONCALL_SHIFT_EMAIL_LOOKBACK_SECONDS = settings.get_int(
        "oncall",
        "shift_email_lookback_seconds", 300)

    BROWSER_PUSH_ENABLED = settings.get_bool(
        "browser_push",
        "enabled",
        False,
    )

    BROWSER_PUSH_VAPID_PUBLIC_KEY = settings.get(
        "browser_push",
        "vapid_public_key",
        "",
    )

    BROWSER_PUSH_VAPID_PRIVATE_KEY = settings.get(
        "browser_push",
        "vapid_private_key",
        "",
    )

    BROWSER_PUSH_VAPID_SUBJECT = settings.get(
        "browser_push",
        "vapid_subject",
        "mailto:admin@example.com",
    )

    BROWSER_PUSH_ACTION_TOKEN_TTL_SECONDS = settings.get_int(
        "browser_push",
        "action_token_ttl_seconds",
        900,
    )

    ALERT_GROUP_WAIT_SECONDS = settings.get_int(
        "alerts",
        "alert_group_wait_seconds",
        30,
    )

    ALERT_GROUP_INTERVAL_SECONDS = settings.get_int(
        "alerts",
        "alert_group_interval_seconds",
        300,
    )

    ALERT_GROUP_NOTIFICATION_CHECK_INTERVAL_SECONDS = settings.get_int(
        "alerts",
        "alert_group_notification_check_interval_seconds",
        10,
    )

    ALERT_GROUP_NOTIFICATION_BATCH_SIZE = settings.get_int(
        "alerts",
        "alert_group_notification_batch_size",
        100,
    )

    INCIDENT_RESPONDER_EXPIRE_CHECK_INTERVAL_SECONDS = settings.get_int(
        "incidents",
        "responder_expire_check_interval_seconds",
        30,
    )

    INCIDENT_RESPONDER_EXPIRE_BATCH_SIZE = settings.get_int(
        "incidents",
        "responder_expire_batch_size",
        100,
    )

    INCIDENT_RESPONDER_DEFAULT_EXPIRES_AFTER_MINUTES = settings.get_int(
        "incidents",
        "responder_default_expires_after_minutes",
        30,
    )

