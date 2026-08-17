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

    SECRET_KEY = settings.get("main", "secret_key", "") or ""
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
    LOG_SLACK_WORKER_FILE = settings.get(
        "logging",
        "slack_worker_file",
        "./logs/incidentrelay-slack-worker.log",
    )
    LOG_LEVEL = settings.get("logging", "level", "INFO")
    LOG_REQUESTS = False

    API_AUTH_REQUIRED = settings.get_bool("auth", "api_auth_required", False)
    RBAC_ENFORCED = settings.get_bool("auth", "rbac_enforced", False)
    JWT_SECRET_KEY = settings.get("auth", "jwt_secret", SECRET_KEY) or SECRET_KEY
    JWT_EXPIRE_MINUTES = settings.get_int("auth", "jwt_expire_minutes", 1440)
    JWT_COOKIE_NAME = settings.get("auth", "jwt_cookie_name", "incidentrelay_jwt")
    JWT_COOKIE_SECURE = settings.get_bool("auth", "jwt_cookie_secure", False)
    AUTH_LOGIN_IP_MAX_FAILURES = settings.get_int(
        "auth", "login_ip_max_failures", 60
    )
    AUTH_LOGIN_IP_WINDOW_SECONDS = settings.get_int(
        "auth", "login_ip_window_seconds", 60
    )
    AUTH_LOGIN_IP_BLOCK_SECONDS = settings.get_int(
        "auth", "login_ip_block_seconds", 60
    )
    AUTH_LOGIN_ACCOUNT_MAX_FAILURES = settings.get_int(
        "auth", "login_account_max_failures", 20
    )
    AUTH_LOGIN_ACCOUNT_WINDOW_SECONDS = settings.get_int(
        "auth", "login_account_window_seconds", 300
    )
    AUTH_LOGIN_ACCOUNT_BLOCK_SECONDS = settings.get_int(
        "auth", "login_account_block_seconds", 300
    )

    SECRET_ENCRYPTION_KEY = settings.get("main", "secret_encryption_key", SECRET_KEY) or SECRET_KEY
    SSO_SECRET_ENCRYPTION_KEY = settings.get("sso", "secret_encryption_key", SECRET_ENCRYPTION_KEY) or SECRET_ENCRYPTION_KEY

    REMINDER_INTERVAL_SECONDS = settings.get_int("alerts", "reminder_interval_seconds", 60)
    ALERT_GROUP_WINDOW_SECONDS = settings.get_int("alerts", "alert_group_window_seconds", 3600)
    MAINTENANCE_LIFECYCLE_CHECK_INTERVAL_SECONDS = settings.get_int(
        "maintenance", "lifecycle_check_interval_seconds", 30
    )
    MAINTENANCE_LIFECYCLE_BATCH_SIZE = settings.get_int(
        "maintenance", "lifecycle_batch_size", 500
    )

    SCHEDULER_LOCK_TTL_SECONDS = settings.get_int("scheduler", "lock_ttl_seconds", 120)
    ORCHESTRATION_PENDING_CHECK_INTERVAL_SECONDS = settings.get_int(
        "orchestration", "pending_check_interval_seconds", 10
    )
    ORCHESTRATION_PENDING_BATCH_SIZE = settings.get_int(
        "orchestration", "pending_batch_size", 100
    )
    ORCHESTRATION_PENDING_CLAIM_TTL_SECONDS = settings.get_int(
        "orchestration", "pending_claim_ttl_seconds", 300
    )
    ORCHESTRATION_PENDING_MAX_ATTEMPTS = settings.get_int(
        "orchestration", "pending_max_attempts", 5
    )
    ORCHESTRATION_PENDING_RETRY_BASE_SECONDS = settings.get_int(
        "orchestration", "pending_retry_base_seconds", 30
    )
    ORCHESTRATION_DROPPED_TRACE_RETENTION_DAYS = settings.get_int(
        "orchestration", "dropped_trace_retention_days", 7
    )
    ORCHESTRATION_PENDING_EVENT_RETENTION_DAYS = settings.get_int(
        "orchestration", "pending_event_retention_days", 30
    )
    ORCHESTRATION_RETENTION_CLEANUP_INTERVAL_SECONDS = settings.get_int(
        "orchestration", "retention_cleanup_interval_seconds", 86400
    )
    ORCHESTRATION_WEBHOOK_CHECK_INTERVAL_SECONDS = settings.get_int(
        "orchestration", "webhook_check_interval_seconds", 5
    )
    ORCHESTRATION_WEBHOOK_BATCH_SIZE = settings.get_int(
        "orchestration", "webhook_batch_size", 50
    )
    ORCHESTRATION_WEBHOOK_CLAIM_TTL_SECONDS = settings.get_int(
        "orchestration", "webhook_claim_ttl_seconds", 300
    )
    ORCHESTRATION_WEBHOOK_RETRY_BASE_SECONDS = settings.get_int(
        "orchestration", "webhook_retry_base_seconds", 30
    )
    ORCHESTRATION_WEBHOOK_MAX_RESPONSE_BYTES = settings.get_int(
        "orchestration", "webhook_max_response_bytes", 65536
    )
    ORCHESTRATION_WEBHOOK_MAX_REDIRECTS = settings.get_int(
        "orchestration", "webhook_max_redirects", 3
    )
    ORCHESTRATION_WEBHOOK_ALLOW_HTTP = settings.get_bool(
        "orchestration", "webhook_allow_http", False
    )
    ORCHESTRATION_WEBHOOK_PRIVATE_NETWORK_ALLOWLIST = settings.get(
        "orchestration", "webhook_private_network_allowlist", ""
    )
    ORCHESTRATION_WEBHOOK_PER_GROUP_CONCURRENCY = settings.get_int(
        "orchestration", "webhook_per_group_concurrency", 2
    )
    ORCHESTRATION_WEBHOOK_PER_GROUP_RATE_PER_MINUTE = settings.get_int(
        "orchestration", "webhook_per_group_rate_per_minute", 60
    )
    ORCHESTRATION_WEBHOOK_EXECUTION_RETENTION_DAYS = settings.get_int(
        "orchestration", "webhook_execution_retention_days", 30
    )
    ORCHESTRATION_REPLAY_MAX_EVENTS = settings.get_int(
        "orchestration", "replay_max_events", 100
    )
    ORCHESTRATION_REPLAY_DROP_WARNING_PERCENT = settings.get_int(
        "orchestration", "replay_drop_warning_percent", 20
    )
    ORCHESTRATION_TRACE_MAX_DEPTH = settings.get_int(
        "orchestration", "trace_max_depth", 12
    )
    ORCHESTRATION_TRACE_MAX_STRING_CHARS = settings.get_int(
        "orchestration", "trace_max_string_chars", 2048
    )
    ORCHESTRATION_TRACE_MAX_ITEMS = settings.get_int(
        "orchestration", "trace_max_items", 512
    )
    ORCHESTRATION_SIMULATION_MAX_PAYLOAD_BYTES = settings.get_int(
        "orchestration", "simulation_max_payload_bytes", 1048576
    )
    ORCHESTRATION_SIMULATION_MAX_DIFFS = settings.get_int(
        "orchestration", "simulation_max_diffs", 512
    )
    ORCHESTRATION_SHADOW_METRICS_MAX_EXECUTIONS = settings.get_int(
        "orchestration", "shadow_metrics_max_executions", 5000
    )
    USER_NOTIFICATION_RULES_CHECK_INTERVAL_SECONDS = settings.get_int(
        "scheduler",
        "user_notification_rules_check_interval_seconds",
        30,
    )

    MATTERMOST_ACTION_SECRET = settings.get("mattermost", "action_secret", SECRET_KEY) or SECRET_KEY
    MATTERMOST_API_URL = settings.get("mattermost", "api_url", "")
    MATTERMOST_BOT_TOKEN = settings.get("mattermost", "bot_token", "")
    MATTERMOST_BOT_USER_ID = settings.get("mattermost", "bot_user_id", "")

    SMTP_HOST = settings.get("smtp", "host", "")
    SMTP_PORT = settings.get_int("smtp", "port", 587)
    SMTP_USER = settings.get("smtp", "user", "")
    SMTP_PASSWORD = settings.get("smtp", "password", "")
    SMTP_FROM = settings.get("smtp", "from", "incidentrelay@example.com")
    SMTP_USE_TLS = settings.get_bool("smtp", "use_tls", True)

    VOICE_PROVIDER = settings.get("voice", "provider", "stub")
    VOICE_CALLBACK_SECRET = settings.get("voice", "callback_secret", SECRET_KEY) or SECRET_KEY
    VOICE_TEXT_TEMPLATE = settings.get("voice", "text_template", "")
    VOICE_DTMF_ACTIONS = settings.get_json(
        "voice",
        "dtmf_actions",
        {"1": "acknowledge", "2": "resolve"},
    )
    VOICE_PROVIDER_CONFIG = settings.get_section("voice_provider", {})

    OUTBOUND_HTTP_PRIVATE_NETWORK_ALLOWLIST = settings.get(
        "security",
        "outbound_private_network_allowlist",
        "",
    )
    OUTBOUND_HTTP_MAX_REDIRECTS = settings.get_int(
        "security",
        "outbound_http_max_redirects",
        3,
    )
    OUTBOUND_HTTP_MAX_RESPONSE_BYTES = settings.get_int(
        "security",
        "outbound_http_max_response_bytes",
        1048576,
    )

    TELEGRAM_PROXY_URL = settings.get("telegram", "proxy_url", "")

    ONCALL_SHIFT_EMAIL_CHECK_INTERVAL_SECONDS = settings.get_int(
        "oncall",
        "shift_email_check_interval_seconds", 60)

    ONCALL_SHIFT_EMAIL_LOOKBACK_SECONDS = settings.get_int(
        "oncall",
        "shift_email_lookback_seconds", 300)

    ONCALL_SHIFT_MATTERMOST_ENABLED = settings.get_bool(
        "oncall",
        "shift_mattermost_enabled", True)

    ONCALL_SHIFT_MATTERMOST_CHECK_INTERVAL_SECONDS = settings.get_int(
        "oncall",
        "shift_mattermost_check_interval_seconds", 60)

    ONCALL_SHIFT_MATTERMOST_LOOKBACK_SECONDS = settings.get_int(
        "oncall",
        "shift_mattermost_lookback_seconds", 300)

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


    SILENCE_LIFECYCLE_CHECK_INTERVAL_SECONDS = settings.get_int(
        "alerts",
        "silence_lifecycle_check_interval_seconds",
        30,
    )

    ALERT_EXPLAIN_TRACE_RETENTION_DAYS = settings.get_int(
        "alerts",
        "alert_explain_trace_retention_days",
        30,
    )

    ALERT_EXPLAIN_TRACE_CLEANUP_INTERVAL_SECONDS = settings.get_int(
        "scheduler",
        "alert_explain_trace_cleanup_interval_seconds",
        86400,
    )

    SERVICE_IMPACT_SNAPSHOT_ENABLED = settings.get_bool(
        "services",
        "impact_snapshot_enabled",
        True,
    )

    SERVICE_IMPACT_SNAPSHOT_INTERVAL_SECONDS = settings.get_int(
        "services",
        "impact_snapshot_interval_seconds",
        300,
    )

    SERVICE_IMPACT_SNAPSHOT_RETENTION_DAYS = settings.get_int(
        "services",
        "impact_snapshot_retention_days",
        365,
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

INSECURE_DEFAULT_SECRETS = frozenset({
    "dev-secret-key",
    "change-me",
    "change-this-secret-key",
    "change-this-jwt-secret",
    "change-this-mattermost-action-secret",
})


def validate_security_configuration(config=Config):
    """Reject empty or shipped authentication secrets before the service starts."""
    required = {
        "main.secret_key": getattr(config, "SECRET_KEY", ""),
        "auth.jwt_secret": getattr(config, "JWT_SECRET_KEY", ""),
    }
    for name, raw_value in required.items():
        value = str(raw_value or "").strip()
        if not value or value in INSECURE_DEFAULT_SECRETS:
            raise RuntimeError(
                f"insecure IncidentRelay secret configuration: {name} must be set "
                "to a unique cryptographically random value"
            )


validate_security_configuration()
