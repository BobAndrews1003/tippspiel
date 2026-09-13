#!/usr/bin/env sh

set -eu

APP_PROJECT_DIR="$(
    CDPATH= cd -- "$(dirname -- "$0")/.." \
        && pwd
)"

ACCEPTANCE_TEMP_DIR="$(
    mktemp -d "${TMPDIR:-/tmp}/puntero-acceptance.XXXXXX"
)"

cleanup_acceptance_dir() {
    acceptance_dir_name="$(
        basename -- "$ACCEPTANCE_TEMP_DIR"
    )"

    case "$acceptance_dir_name" in
        puntero-acceptance.*)
            rm -rf -- "$ACCEPTANCE_TEMP_DIR"
            ;;
        *)
            echo "Temporäres Abnahmeverzeichnis wird aus Sicherheitsgründen nicht entfernt: $ACCEPTANCE_TEMP_DIR" >&2
            ;;
    esac
}

trap cleanup_acceptance_dir EXIT HUP INT TERM

cd "$APP_PROJECT_DIR"

if [ -x "$APP_PROJECT_DIR/.venv/bin/python" ]; then
    ACCEPTANCE_PYTHON="$APP_PROJECT_DIR/.venv/bin/python"
else
    ACCEPTANCE_PYTHON="python"
fi

export DEBUG=1
export SECRET_KEY="django-insecure-release-acceptance-only"
export DATABASE_URL="sqlite:///$ACCEPTANCE_TEMP_DIR/acceptance.sqlite3"
export DATABASE_CONN_MAX_AGE=0
export DATABASE_SSL_REQUIRED=0
export REDIS_URL=
export CACHE_KEY_PREFIX="puntero-acceptance"

export EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
export EMAIL_HOST=
export EMAIL_HOST_USER=
export EMAIL_HOST_PASSWORD=
export EMAIL_USE_TLS=0
export EMAIL_USE_SSL=0
export DEFAULT_FROM_EMAIL="Puntero <noreply@acceptance.invalid>"
export SERVER_EMAIL="Puntero <noreply@acceptance.invalid>"
export ACCOUNT_EMAIL_VERIFICATION=mandatory
export ACCOUNT_EMAIL_NOTIFICATIONS=0

export LEGAL_PAGES_ENABLED=0
export LEGAL_REVIEW_CONFIRMED=0
export TIP_REMINDERS_ENABLED=0
export ACCOUNT_RETENTION_NOTICES_ENABLED=0

echo "Erstelle eine isolierte Abnahmedatenbank ..."
"$ACCEPTANCE_PYTHON" manage.py migrate \
    --noinput \
    --verbosity 0

echo "Prüfe die isolierte Django-Konfiguration ..."
"$ACCEPTANCE_PYTHON" manage.py check

echo "Führe den Ende-zu-Ende-Abnahmetest aus ..."
"$ACCEPTANCE_PYTHON" manage.py test \
    tipping.tests.test_release_acceptance \
    --verbosity 2

echo "Lokale Release-Abnahme erfolgreich."
