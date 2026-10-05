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
# config changes take effect; only the generated keys are kept from it.
if [ "$CONFIG_FILE" = "/etc/incidentrelay/incidentrelay.conf" ]; then
  RUNTIME_CONFIG="/var/lib/incidentrelay/incidentrelay.conf"
  python - "$CONFIG_FILE" "$RUNTIME_CONFIG" <<'PY_CONFIG'
import configparser
import fcntl
import os
import secrets
import sys
import tempfile

source, target = sys.argv[1], sys.argv[2]
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

    # Stored secrets are encrypted with this key; a new one would make them
    # unreadable, so keep the key this installation has been using.
    stored_key = stored.get("main", "secret_encryption_key", fallback="").strip()
    if (
        not from_env("main", "secret_encryption_key")
        and stored_key not in known_insecure
        and parser.get("main", "secret_encryption_key") != stored_key
    ):
        print(
            "WARNING: main.secret_encryption_key differs from the key this installation "
            f"has been using; keeping the stored key from {target} so encrypted data "
            "stays readable.",
            file=sys.stderr,
        )
        parser.set("main", "secret_encryption_key", stored_key)

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
