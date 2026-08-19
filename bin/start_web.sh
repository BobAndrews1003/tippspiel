#!/usr/bin/env sh

set -eu

APP_PROJECT_DIR="$(
    CDPATH= cd -- "$(dirname -- "$0")/.." \
        && pwd
)"

cd "$APP_PROJECT_DIR"

APP_PORT="${PORT:-8000}"
APP_WORKERS="${WEB_CONCURRENCY:-2}"
APP_TIMEOUT="${GUNICORN_TIMEOUT:-30}"

echo "Sammle statische Dateien ..."
python manage.py collectstatic --noinput

echo "Starte Gunicorn auf Port ${APP_PORT} ..."
exec gunicorn tippspiel.wsgi:application \
    --bind "0.0.0.0:${APP_PORT}" \
    --workers "$APP_WORKERS" \
    --timeout "$APP_TIMEOUT" \
    --access-logfile - \
    --error-logfile -
