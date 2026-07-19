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
