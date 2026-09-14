# Puntero

Puntero ist ein Django-Tippspiel mit Gruppen, Spieltags- und
Bonustipps sowie vorberechneten Ranglisten. Die Produktionsarchitektur
besteht aus einem Webprozess, einem separaten Standing-Worker,
PostgreSQL und Redis.

## Voraussetzungen

- Python 3.13.5
- Git
- Für die Produktion: PostgreSQL, Redis und ein SMTP-Konto

Die Python-Version ist in `.python-version` festgelegt. Alle direkten
Python-Abhängigkeiten sind mit exakten Versionen in `requirements.txt`
fixiert.

## Lokale Einrichtung

```sh
git clone <REPOSITORY-URL>
cd tippspiel
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Die lokale `.env` wird automatisch geladen und nicht versioniert.
Standardmäßig werden SQLite, ein prozesslokaler Cache und das
Console-E-Mail-Backend verwendet. Die Anwendung ist anschließend unter
`http://127.0.0.1:8000/` erreichbar.

Der Hintergrund-Worker läuft in einem zweiten Terminal:

```sh
. .venv/bin/activate
bin/start_standing_worker.sh
```

## Release-Prüfung

Der vollständige lokale Prüfablauf ist in einem Befehl reproduzierbar:

```sh
bin/check_release.sh
```

Das Skript prüft Git-Diffs, Django-Konfiguration, fehlende Migrationen,
statische Dateien und die vollständige Testsuite. Es verwendet bewusst
SQLite und den lokalen Cache, damit niemals versehentlich eine
Produktionsdatenbank für Tests verwendet wird.

Zusätzlich prüft eine kleine Ende-zu-Ende-Abnahme die wichtigsten
Nutzerwege in einem zusammenhängenden Szenario. Dabei werden eine
temporäre SQLite-Datenbank und ein E-Mail-Backend ohne externen Versand
verwendet:

```sh
bin/check_acceptance.sh
```

Die ergänzende manuelle Produktprüfung ist in
[`docs/release-acceptance.md`](docs/release-acceptance.md) dokumentiert.

Die vorbereiteten, standardmäßig deaktivierten Gruppenpläne Free, Plus
und Club sowie der noch fehlende Weg zur Zahlungsabwicklung sind in
[`docs/group-plans.md`](docs/group-plans.md) beschrieben.

## Produktionsarchitektur auf Railway

In einem Railway-Projekt werden vier Services angelegt:

1. `web`: öffentlich erreichbare Django-Anwendung
2. `standing-worker`: privater Hintergrundprozess
3. `Postgres`: gemeinsame Produktionsdatenbank
4. `Redis`: gemeinsamer Cache und Grundlage der Auth-Rate-Limits

Web und Worker verwenden dasselbe Repository und denselben Commit.
Nur der Webservice erhält eine öffentliche Domain.

### 1. Webservice konfigurieren

Repository mit dem Service verbinden und als Config-as-Code-Pfad
`/railway.web.json` einstellen. Diese Konfiguration führt vor jedem
Deployment zuerst den Django-Produktionscheck und anschließend genau
einmal

```sh
python manage.py check --deploy --fail-level ERROR
python manage.py migrate --noinput
```

aus. Danach sammelt `bin/start_web.sh` die statischen Dateien und
startet Gunicorn auf Railways `PORT`.

Railway gibt den neuen Deployment-Traffic erst frei, wenn `/health/`
HTTP 200 liefert. Der Healthcheck prüft Webprozess, PostgreSQL und Redis,
ohne interne Fehlerdetails nach außen zu geben.

### 2. Worker konfigurieren

Einen zweiten Service aus demselben Repository anlegen und als
Config-as-Code-Pfad `/railway.worker.json` einstellen. Der Worker startet
mit `bin/start_standing_worker.sh` und wartet, bis die Webmigration das
Datenbankschema aktualisiert hat.

Migrationen dürfen nicht zusätzlich im Worker als Pre-Deploy-Befehl
konfiguriert werden. Dadurch werden parallele Migrationsläufe vermieden.

### 3. Gemeinsame Produktionsvariablen

Die folgenden Variablen müssen im Web- und Worker-Service gesetzt sein:

| Variable | Beispiel oder Bedeutung |
| --- | --- |
| `DEBUG` | `0` |
| `SECRET_KEY` | mindestens 50 zufällige Zeichen |
| `ALLOWED_HOSTS` | `app.example.com` |
| `CSRF_TRUSTED_ORIGINS` | `https://app.example.com` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `DATABASE_SSL_REQUIRED` | `1` |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` |
| `CACHE_KEY_PREFIX` | eindeutiger Wert, zum Beispiel `puntero-prod` |
| `TRUST_X_FORWARDED_PROTO` | `1` |
| `ACCOUNT_EMAIL_VERIFICATION` | `mandatory` |
| `ACCOUNT_EMAIL_NOTIFICATIONS` | `1` |
| `DEFAULT_FROM_EMAIL` | zum Beispiel `Puntero <noreply@example.com>` |
| `EMAIL_HOST` | SMTP-Hostname |
| `EMAIL_PORT` | normalerweise `587` |
| `EMAIL_HOST_USER` | SMTP-Benutzer |
| `EMAIL_HOST_PASSWORD` | SMTP-Passwort |
| `EMAIL_USE_TLS` | normalerweise `1` |
| `EMAIL_USE_SSL` | normalerweise `0` |
| `PUBLIC_BASE_URL` | öffentliche HTTPS-Adresse, zum Beispiel `https://app.example.com` |
| `TIP_REMINDERS_ENABLED` | `1`, sobald der automatische Versand freigegeben ist |
| `ACCOUNT_RETENTION_NOTICES_ENABLED` | zunächst `0`; erst nach geprüftem Testversand auf `1` setzen |
| `LOG_LEVEL` | `INFO` |

`ALLOWED_HOSTS` enthält nur Hostnamen ohne Schema. Die Einträge in
`CSRF_TRUSTED_ORIGINS` enthalten dagegen immer `https://`. Mehrere Werte
werden jeweils durch Kommas getrennt.

Nur der Webservice benötigt zusätzlich:

| Variable | Standard |
| --- | --- |
| `WEB_CONCURRENCY` | `2` |
| `GUNICORN_TIMEOUT` | `30` |

Optionale Worker-Anpassungen:

| Variable | Standard |
| --- | --- |
| `MIGRATION_WAIT_SECONDS` | `5` |
| `MIGRATION_WAIT_ATTEMPTS` | `60` |
| `STANDING_JOB_BATCH_SIZE` | `10` |
| `STANDING_JOB_POLL_SECONDS` | `2` |
| `STANDING_JOB_STALE_MINUTES` | `60` |
| `TIP_REMINDER_LEAD_HOURS` | `24` |
| `TIP_REMINDER_POLL_SECONDS` | `300` |
| `ACCOUNT_RETENTION_FIRST_NOTICE_DAYS` | `30` |
| `ACCOUNT_RETENTION_FINAL_NOTICE_DAYS` | `7` |
| `ACCOUNT_RETENTION_NOTICE_BATCH_SIZE` | `100` |
| `ACCOUNT_RETENTION_NOTICE_POLL_SECONDS` | `86400` |
| `ACCOUNT_RETENTION_NOTICE_CLAIM_STALE_MINUTES` | `60` |

Der `standing-worker` prüft zusätzlich auf fällige Tipperinnerungen.
Deshalb darf genau ein solcher Worker laufen. Nutzer müssen die Option
unter `Perfil` → `Recordatorios` selbst aktivieren. Der Versand erfolgt
nur an eine bestätigte E-Mail-Adresse und wird je Nutzer, Gruppe und
Spiel protokolliert.

Der zufällige Secret Key kann lokal erzeugt und anschließend als
Railway-Secret eingetragen werden:

```sh
python -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Echte Zugangsdaten gehören ausschließlich in Railway-Variablen und
niemals in `.env.example`, Commits, Logs oder Tickets.

## Rechtliche Seiten als geschützte Entwürfe

Die spanischen Seiten `/privacidad/`, `/terminos/` und `/contacto/` sind
in der Anwendung vorbereitet, bleiben aber standardmäßig deaktiviert.
Solange `LEGAL_PAGES_ENABLED=0` gilt, antworten die URLs mit HTTP 404 und
es erscheinen weder im Menü noch im Footer Links darauf.

Zur lokalen Vorschau kann in `.env` vorübergehend gesetzt werden:

```sh
LEGAL_PAGES_ENABLED=1
```

Die Entwürfe zeigen dann einen deutlichen Hinweis und werden mit
`noindex,nofollow` ausgeliefert, solange mindestens ein Wert leer ist
oder mit `[COMPLETAR:` beginnt. Folgende Angaben sind vor einer
fachlichen und juristischen Endprüfung zu ersetzen:

| Variable | Benötigte Angabe |
| --- | --- |
| `LEGAL_OPERATOR_NAME` | vollständiger Betreibername |
| `LEGAL_OPERATOR_ADDRESS` | zustellfähige Anschrift in Ecuador |
| `LEGAL_OPERATOR_PHONE` | Telefonnummer |
| `LEGAL_CONTACT_EMAIL` | Datenschutz- und Kontakt-E-Mail |
| `LEGAL_HOSTING_REGION` | endgültige Railway-Region |
| `LEGAL_COMMERCIAL_MODEL` | Entscheidung zu Preisen, Werbung und Sponsoring |
| `LEGAL_MATCH_EXCEPTION_RULE` | Regel für ausgesetzte oder verlegte Spiele |
| `LEGAL_PAGES_LAST_UPDATED` | Datum der freigegebenen Fassung |

Eine Produktionsumgebung startet nicht, wenn die Seiten aktiviert sind
und noch ein Platzhalter vorhanden ist oder
`LEGAL_REVIEW_CONFIRMED=1` fehlt. Dieser Schalter darf erst nach der
inhaltlichen Endprüfung gesetzt werden. Die technische Sperre ersetzt
keine juristische Beratung.

## Deployment-Ablauf

1. Release-Prüfung mit `bin/check_release.sh` ausführen.
2. Geprüften Commit in das mit Railway verbundene Repository pushen.
3. Web-Pre-Deploy-Logs kontrollieren: Migrationen müssen erfolgreich
   abgeschlossen sein.
4. Web-Start und erfolgreichen `/health/`-Check kontrollieren.
5. Worker-Logs kontrollieren: Schema aktuell, Worker gestartet.
6. Einen Smoke-Test durchführen: Login, Gruppe, Tippabgabe und Tabelle.

Ein fehlgeschlagener Pre-Deploy-Befehl verhindert die Freigabe des neuen
Web-Deployments. Der Worker wird durch Railway automatisch neu gestartet,
wenn sein Prozess beendet wird.

## Betrieb

### Standing-Jobs

Ein einzelner Durchlauf kann manuell ausgeführt werden:

```sh
python manage.py process_standing_jobs --limit 10
```

Fehlgeschlagene Jobs werden nach Ursachenanalyse erneut freigegeben mit:

```sh
python manage.py process_standing_jobs --retry-failed --limit 10
```

### Tipperinnerungen

Vor der Aktivierung kann die Auswahl ohne Versand geprüft werden:

```sh
python manage.py send_tip_reminders --dry-run
```

Danach werden `PUBLIC_BASE_URL` auf die öffentliche HTTPS-Adresse und
`TIP_REMINDERS_ENABLED=1` im Worker gesetzt. Der Versand verwendet die
oben konfigurierte SMTP-Verbindung. Zum kontrollierten Einzeltest kann
der Befehl auch einmal manuell ausgeführt werden:

```sh
python manage.py send_tip_reminders
```

Der reguläre Betrieb erfolgt automatisch im `standing-worker`. Fehler
bei Erinnerungen stoppen die Standing-Verarbeitung nicht; sie werden im
Worker-Log ohne E-Mail-Adresse ausgegeben und beim nächsten Lauf erneut
versucht.

### Datenaufbewahrung

Die Anwendung verwendet folgende Standardfristen:

| Daten | Frist |
| --- | --- |
| Unbestätigte Registrierung ohne Spieldaten | 14 Tage |
| Bestätigtes, nicht mehr genutztes Konto | 730 Tage; derzeit nur Meldung |
| Inaktive Gruppenmitgliedschaft und zugehörige Tipps | 365 Tage |
| Nachweis einer versendeten Tipperinnerung | 90 Tage |
| Anmeldung/Sitzung | höchstens 14 Tage |
| E-Mail-Bestätigungslink | 3 Tage |
| Passwort-Zurücksetzungslink | 1 Stunde |

Vor jeder Löschung wird der ungefährliche Prüfmodus ausgeführt:

```sh
python manage.py cleanup_personal_data
```

Erst nach Kontrolle der Ausgabe und einem geprüften Backup wird die
Bereinigung ausdrücklich freigegeben:

```sh
python manage.py cleanup_personal_data --execute
```

Pro Lauf werden höchstens 500 Hauptdatensätze je Kategorie ausgewählt;
abhängige Daten einer ausgewählten Mitgliedschaft werden vollständig
mitgelöscht. Mit `--limit` kann diese Batchgröße angepasst werden. Gruppenbesitzer,
Administratoren und unbestätigte Konten mit Spieldaten werden nicht
automatisch gelöscht. Bestätigte Konten nach 730 Tagen werden bislang nur
gemeldet und noch nicht gelöscht.

Die Benachrichtigungen 30 und 7 Tage vor einer späteren Kontolöschung
sind vorbereitet. Ihre Auswahl lässt sich ohne Versand prüfen:

```sh
python manage.py send_account_retention_notices
```

Ein echter Versand benötigt gleichzeitig den globalen Schalter
`ACCOUNT_RETENTION_NOTICES_ENABLED=1` und die ausdrückliche Option:

```sh
python manage.py send_account_retention_notices --execute
```

Nach einer erfolgreichen ersten Warnung wartet das System mindestens 23
Tage bis zur letzten Warnung. Eine verspätete erste Warnung gewährt immer
noch mindestens 30 Tage; dadurch wird eine spätere Löschung entsprechend
verschoben. Ein erfolgreicher Login beendet den Warnzyklus sofort.

Wenn der globale Schalter aktiviert ist, übernimmt der vorhandene
`standing-worker` die Prüfung einmal täglich. Es ist dafür kein weiterer
Railway-Service erforderlich. Vor der Aktivierung müssen beide
E-Mail-Stufen mit dem Produktions-SMTP-Konto getestet werden. Die spätere
Kontolöschung selbst bleibt gesperrt, bis sie zusätzlich an zwei
erfolgreich versendete Warnungen gekoppelt und separat geprüft wurde.

Der eigentliche Bereinigungsbefehl `cleanup_personal_data` ist noch nicht
automatisch eingeplant. Nach einem erfolgreichen Prüf- und Backup-Lauf
kann er als täglicher Railway-Cronjob mit `--execute` eingerichtet werden.

Die Produktionsüberwachung sollte mindestens alarmieren bei:

- nicht erreichbarem `/health/`-Endpoint,
- wiederholt neu startendem Web- oder Workerprozess,
- fehlgeschlagenen oder lange laufenden Standing-Jobs,
- Datenbank- oder Redis-Verbindungsfehlern,
- ungewöhnlich vielen HTTP-500- oder Auth-Fehlern.

### Backups und Wiederherstellung

PostgreSQL-Backups werden beim Datenbankanbieter aktiviert. Vor dem
Go-live und vor destruktiven Migrationen muss eine Wiederherstellung in
eine getrennte Testdatenbank praktisch geprüft werden. Ein Backup gilt
erst dann als verlässlich, wenn dieser Restore-Test erfolgreich war.

Lokale SQLite-Dateien, `staticfiles/`, `media/`, `.env` und
`__pycache__/` sind keine Release-Artefakte und werden nicht committet.

### Rollback

Bei einem reinen Codefehler wird in Railway das letzte funktionierende
Deployment erneut bereitgestellt. Datenbankmigrationen werden nicht
blind rückwärts ausgeführt. Bei nicht rückwärtskompatiblen Migrationen
wird entweder ein geprüfter Daten-Fix vorwärts ausgerollt oder aus einem
vorher getesteten Backup wiederhergestellt.

## Wichtige Referenzen

- [Railway: Django bereitstellen](https://docs.railway.com/guides/django)
- [Railway: Config as Code](https://docs.railway.com/config-as-code)
- [Railway: Pre-Deploy Commands](https://docs.railway.com/deployments/pre-deploy-command)
- [Railpack: Python](https://railpack.com/languages/python)
