#!/usr/bin/env bash
set -euo pipefail

# Prefer the correctly-spelled env var; fall back to the legacy mis-spelled
# one so existing deployments keep working until operators migrate.
if [ -n "${INCEDENTRELAY_CONFIG_FILE:-}" ] && [ -z "${INCIDENTRELAY_CONFIG_FILE:-}" ]; then
  echo "WARNING: environment variable INCEDENTRELAY_CONFIG_FILE is deprecated (typo); please use INCIDENTRELAY_CONFIG_FILE instead." >&2
fi
CONFIG_FILE="${INCIDENTRELAY_CONFIG_FILE:-${INCEDENTRELAY_CONFIG_FILE:-/etc/incidentrelay/incidentrelay.conf}}"
SERVICE="${INCIDENTRELAY_SERVICE:-web}"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Config file not found: $CONFIG_FILE"
  exit 1
fi

# The stock image config intentionally contains no reusable authentication
# secrets. Create one persistent runtime config on the shared data volume so
# web/scheduler/notifier processes all use the same random keys across restarts.
# The runtime config is rebuilt from the mounted config on every start, so
# config changes take effect; shared keys the mounted config leaves empty are
# carried over from the previous copy.
if [ "$CONFIG_FILE" = "/etc/incidentrelay/incidentrelay.conf" ]; then
  RUNTIME_CONFIG="/var/lib/incidentrelay/incidentrelay.conf"
  python - "$CONFIG_FILE" "$RUNTIME_CONFIG" <<'PY_CONFIG'
import configparser
import fcntl
import hashlib
import hmac
import os
import secrets
import sys
import tempfile

source, target = sys.argv[1], sys.argv[2]
KEY_CHECK_ITERATIONS = 200_000
os.makedirs(os.path.dirname(target), exist_ok=True)
lock_path = target + ".lock"
known_insecure = {
    "",
    "dev-secret-key",
    "change-me",
    "change-this-secret-key",
    "change-this-jwt-secret",
    "change-this-mattermost-action-secret",
}

with open(lock_path, "a+", encoding="utf-8") as lock_file:
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(source)
    stored = configparser.ConfigParser()
    stored.optionxform = str
    if os.path.exists(target):
        stored.read(target)

    def from_env(section, option):
        # Keys passed as INCIDENTRELAY__<SECTION>__<OPTION>[__FILE] are read
        # by the application from the environment.
        env_name = f"INCIDENTRELAY__{section}__{option}".upper()
        return env_name in os.environ or env_name + "__FILE" in os.environ

    secret_key_from_env = from_env("main", "secret_key")

    def ensure_secret(section, option, inherits_secret_key=True):
        if from_env(section, option):
            return
        if not parser.has_section(section):
            parser.add_section(section)
        current = parser.get(section, option, fallback="").strip()
        if current not in known_insecure:
            return
        previous = stored.get(section, option, fallback="").strip()
        if previous not in known_insecure:
            # Keep the key this installation has been using.
            parser.set(section, option, previous)
        elif inherits_secret_key and secret_key_from_env:
            # Leave it empty: the application falls back to main.secret_key,
            # so every pod uses the same key instead of generating its own.
            parser.set(section, option, "")
        else:
            parser.set(section, option, secrets.token_urlsafe(48))

    ensure_secret("main", "secret_key", inherits_secret_key=False)
    ensure_secret("main", "secret_encryption_key")
    ensure_secret("auth", "jwt_secret")
    ensure_secret("mattermost", "action_secret")
    ensure_secret("voice", "callback_secret")

    def env_value(section, option):
        # The value the application reads from the environment, or None.
        env_name = f"INCIDENTRELAY__{section}__{option}".upper()
        if env_name + "__FILE" in os.environ:
            try:
                with open(os.environ[env_name + "__FILE"], encoding="utf-8") as handle:
                    return handle.read().rstrip("\r\n")
            except OSError:
                # The application reports the unreadable file itself.
                return None
        return os.environ.get(env_name)

    def key_check(key):
        # A salted hash, so a key from the environment is never written here.
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt, KEY_CHECK_ITERATIONS)
        return f"pbkdf2_sha256:{KEY_CHECK_ITERATIONS}:{salt.hex()}:{digest.hex()}"

    def key_matches(key, check):
        _, iterations, salt, digest = check.split(":")
        expected = hashlib.pbkdf2_hmac(
            "sha256", key.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(expected.hex(), digest)

    def is_key_check(check):
        parts = check.split(":")
        return len(parts) == 4 and parts[0] == "pbkdf2_sha256"

    # Secrets in the database are encrypted with main.secret_encryption_key,
    # so it must stay the same across restarts wherever it comes from.
    configured_key = env_value("main", "secret_encryption_key")
    if configured_key is None:
        configured_key = parser.get("main", "secret_encryption_key", fallback="").strip()
    stored_check = stored.get("entrypoint", "secret_encryption_key_check", fallback="")
    if not is_key_check(stored_check):
        # Copies written by earlier versions hold only the key itself.
        stored_key = stored.get("main", "secret_encryption_key", fallback="").strip()
        stored_check = key_check(stored_key) if stored_key not in known_insecure else ""
    if configured_key:
        if stored_check and not key_matches(configured_key, stored_check):
            sys.exit(
                "ERROR: main.secret_encryption_key differs from the key this installation "
                "has been using. Secrets stored in the database are encrypted with it and "
                "would become unreadable, and changing the key directly is not supported. "
                "Restore the previous key."
            )
        stored_check = stored_check or key_check(configured_key)
    if stored_check:
        if not parser.has_section("entrypoint"):
            parser.add_section("entrypoint")
        parser.set("entrypoint", "secret_encryption_key_check", stored_check)

    fd, temp_path = tempfile.mkstemp(
        prefix="incidentrelay-conf-",
        dir=os.path.dirname(target),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
PY_CONFIG
  CONFIG_FILE="$RUNTIME_CONFIG"
  export INCIDENTRELAY_CONFIG_FILE="$CONFIG_FILE"
fi

echo "Using config: $CONFIG_FILE"
echo "Starting IncidentRelay service: $SERVICE"

if [ "${INCIDENTRELAY_RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "Running database migrations..."
  python app/migrate.py migrate
fi

case "$SERVICE" in
  web)
    exec gunicorn \
      --bind "0.0.0.0:${INCIDENTRELAY_PORT:-8080}" \
      --workers "${INCIDENTRELAY_WEB_WORKERS:-1}" \
      --threads "${INCIDENTRELAY_WEB_THREADS:-4}" \
      --timeout "${INCIDENTRELAY_WEB_TIMEOUT:-120}" \
      --access-logfile "-" \
      --error-logfile "-" \
      "app:create_app()"
    ;;

  scheduler)
    exec python -m app.scheduler_worker
    ;;
  telegram)
    exec python -m app.telegram_worker
    ;;
  slack)
    exec python -m app.slack_worker
    ;;
  shell)
    exec /bin/bash
    ;;

  *)
    echo "Unknown INCIDENTRELAY_SERVICE: $SERVICE"
    echo "Allowed values: web, scheduler, telegram, slack, shell"
    exit 1
    ;;
esac
