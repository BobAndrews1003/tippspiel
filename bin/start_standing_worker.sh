#!/usr/bin/env sh

set -eu

APP_PROJECT_DIR="$(
    CDPATH= cd -- "$(dirname -- "$0")/.." \
        && pwd
)"

cd "$APP_PROJECT_DIR"

WAIT_SECONDS="${MIGRATION_WAIT_SECONDS:-5}"
MAX_ATTEMPTS="${MIGRATION_WAIT_ATTEMPTS:-60}"

attempt=1

echo "Prüfe ausstehende Django-Migrationen ..."

while ! python manage.py migrate --check >/dev/null 2>&1
do
    if [ "$attempt" -ge "$MAX_ATTEMPTS" ]
    then
        echo \
            "Datenbankschema ist nach ${MAX_ATTEMPTS} Prüfungen nicht aktuell." \
            >&2
        exit 1
    fi

    echo \
        "Migrationen noch nicht abgeschlossen. Versuch ${attempt}/${MAX_ATTEMPTS}."

    sleep "$WAIT_SECONDS"
    attempt=$((attempt + 1))
done

echo "Datenbankschema ist aktuell."
echo "Starte Standing-Worker ..."

exec python manage.py process_standing_jobs \
    --watch \
    --limit "${STANDING_JOB_BATCH_SIZE:-10}" \
    --poll-seconds "${STANDING_JOB_POLL_SECONDS:-2}" \
    --stale-minutes "${STANDING_JOB_STALE_MINUTES:-60}"
