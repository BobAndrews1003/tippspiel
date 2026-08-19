#!/usr/bin/env sh

set -eu

APP_PROJECT_DIR="$(
    CDPATH= cd -- "$(dirname -- "$0")/.." \
        && pwd
)"

cd "$APP_PROJECT_DIR"

# Die Prüfungen verwenden bewusst eine isolierte lokale
# SQLite-Datenbank und den lokalen Speicher-Cache.
export DEBUG=1
export DATABASE_URL=
export REDIS_URL=

echo "Prüfe Git-Diffs ..."
git diff --check
git diff --cached --check

echo "Prüfe Django-Konfiguration ..."
python manage.py check

echo "Prüfe fehlende Migrationen ..."
python manage.py makemigrations --check --dry-run

echo "Prüfe statische Dateien ..."
python manage.py collectstatic \
    --noinput \
    --dry-run \
    --verbosity 0

echo "Führe Tests aus ..."
python manage.py test tipping.tests

echo "Release-Prüfung erfolgreich."
