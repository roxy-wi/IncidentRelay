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


settings = Settings()


class Config:
    """
    Flask-compatible settings object built from the external config file.
    """

    SECRET_KEY = settings.get("main", "secret_key", "dev-secret-key")
    DB_TYPE = settings.get("database", "type", "sqlite")
    DB_NAME = settings.get("database", "name", "incedentrelay.db")
    DB_USER = settings.get("database", "user", "")
    DB_PASSWORD = settings.get("database", "password", "")
    DB_HOST = settings.get("database", "host", "127.0.0.1")
    DB_PORT = settings.get_int("database", "port", 0)

    DEFAULT_TIMEZONE = settings.get("main", "timezone", "UTC")
    PUBLIC_BASE_URL = settings.get("main", "public_base_url", "http://127.0.0.1:8080")

    API_AUTH_REQUIRED = settings.get_bool("auth", "api_auth_required", False)
    RBAC_ENFORCED = settings.get_bool("auth", "rbac_enforced", False)
    JWT_SECRET_KEY = settings.get("auth", "jwt_secret", SECRET_KEY)
    JWT_EXPIRE_MINUTES = settings.get_int("auth", "jwt_expire_minutes", 1440)
    JWT_COOKIE_NAME = settings.get("auth", "jwt_cookie_name", "incedentrelay_jwt")
    JWT_COOKIE_SECURE = settings.get_bool("auth", "jwt_cookie_secure", False)

    REMINDER_AFTER_SECONDS = settings.get_int("alerts", "reminder_after_seconds", 300)
    REMINDER_INTERVAL_SECONDS = settings.get_int("alerts", "reminder_interval_seconds", 60)
    ALERT_GROUP_WINDOW_SECONDS = settings.get_int("alerts", "alert_group_window_seconds", 3600)

    SCHEDULER_LOCK_TTL_SECONDS = settings.get_int("scheduler", "lock_ttl_seconds", 120)

    LOG_FILE = settings.get("logging", "file", "./logs/incedentrelay.log")
    LOG_LEVEL = settings.get("logging", "level", "INFO")
    LOG_REQUESTS = False

    MATTERMOST_ACTION_SECRET = settings.get("mattermost", "action_secret", SECRET_KEY)

    SMTP_HOST = settings.get("smtp", "host", "")
    SMTP_PORT = settings.get_int("smtp", "port", 587)
    SMTP_USER = settings.get("smtp", "user", "")
    SMTP_PASSWORD = settings.get("smtp", "password", "")
    SMTP_FROM = settings.get("smtp", "from", "incedentrelay@example.com")
    SMTP_USE_TLS = settings.get_bool("smtp", "use_tls", True)
