# Automatischer LigaPro-Spielplan und Live-Scoring

Puntero kann Anstoßzeiten, Live-Zwischenstände und Endergebnisse aus
der öffentlichen Spielplanquelle auf der offiziellen LigaPro-Domain
übernehmen. Die Integration ist standardmäßig ausgeschaltet und wird
erst nach einem erfolgreichen Prüfmodus aktiviert.

## Datenquelle und Freigabe

Verwendet wird derzeit:

```text
https://ligapro.ec/informacion/fixtures/dataPartidos.php
```

Die Quelle liefert stabile Spiel-IDs, Status, Datum, Uhrzeit,
Mannschaften und Spielstände. Sie ist öffentlich erreichbar, aber
nicht als vertraglich garantierte API mit SLA oder ausdrücklich
erteilter Weiterverwendungslizenz dokumentiert. Für den privaten
Testlauf ist sie technisch geeignet. Vor einem öffentlichen oder
kommerziellen Betrieb sollte die dauerhafte Nutzung schriftlich mit
LigaPro geklärt werden.

Der Adapter ist deshalb von der Anwendung getrennt, standardmäßig
deaktiviert und kann später ohne Änderung an Punkteberechnung oder
Tabellen durch einen freigegebenen Datenanbieter ersetzt werden.

## Was die Synchronisation verändert

- Die stabile LigaPro-ID wird einmalig mit der lokalen Partie
  verknüpft.
- Eine vorhandene konkrete Anstoßzeit ersetzt die lokale Zeit.
- Fehlt in der Quelle noch eine Uhrzeit, bleibt der vorhandene lokale
  Platzhalter unverändert.
- Bei `Playing` werden nur separate Live-Spielstände gespeichert.
- Bei `Played` werden die Live-Werte gelöscht und das Endergebnis in
  die bestehenden Ergebnisfelder übernommen.
- Ein bereits bestätigtes Endergebnis wird nicht gelöscht, wenn die
  Quelle vorübergehend wieder einen älteren Status meldet.
- Unbekannte Mannschaften, doppelte IDs, unvollständige Ergebnisse,
  mehrdeutige Zuordnungen und unerwartete Datenmengen stoppen den
  betreffenden Abgleich, statt eine unsichere Zuordnung zu erzwingen.

Live-Werte verändern die dauerhaft gespeicherte Gesamtwertung nicht.
In `Fecha actual` werden während eines Spiels vorläufige Punkte und
Ränge berechnet. Erst ein Endergebnis löst die vorhandene automatische
Punkte- und Tabellenberechnung aus.

## Einmalige lokale Einrichtung

Zuerst die Migration anwenden:

```sh
python manage.py migrate
```

In einer leeren Datenbank wird danach der versionierte Ausgangsspielplan
reproduzierbar importiert:

```sh
python manage.py bootstrap_ligapro
```

Der Befehl importiert 240 reguläre Partien und 72 Partien der drei
Finalphasen. Bei erneutem Aufruf validiert er den vorhandenen Bestand,
ohne Spiele doppelt anzulegen. Ein teilweise befüllter oder
widersprüchlicher Bestand wird nicht automatisch verändert.

Danach immer zuerst den Prüfmodus ausführen:

```sh
python manage.py sync_ligapro
```

Der Befehl lädt und validiert die Quelle, ordnet alle Partien zu und
zeigt die geplanten Änderungen an. Er speichert ohne `--apply` nichts.
Nur wenn keine Partie unter `Nicht zugeordnet`, `Mehrdeutig` oder
`Konflikte` erscheint, werden die Daten übernommen:

```sh
python manage.py sync_ligapro --apply
```

Im Adminbereich sind Quellstatus, Live-Spielstand, Endergebnis,
externe ID und Zeitpunkt des letzten Abgleichs bei jeder Partie
sichtbar. Endergebnisse können bei einem Ausfall der Quelle weiterhin
manuell korrigiert werden.

## Automatischer Betrieb

Der vorhandene `standing-worker` übernimmt den Abgleich; ein weiterer
Railway-Service ist nicht notwendig. Dazu wird ausschließlich im
Worker gesetzt:

```text
LIGAPRO_SYNC_ENABLED=1
```

Standardmäßig prüft der Worker in einem Zeitfenster rund um offene
Spiele alle 120 Sekunden und außerhalb dieses Fensters spätestens alle
sechs Stunden. Diese Werte können angepasst werden:

| Variable | Standard | Bedeutung |
| --- | ---: | --- |
| `LIGAPRO_SYNC_ENABLED` | `0` | Automatischen Abgleich aktivieren |
| `LIGAPRO_SYNC_URL` | offizielle Quelle | Datenquelle |
| `LIGAPRO_SYNC_TOURNAMENT` | `LigaPro Ecuador` | lokaler Turniername |
| `LIGAPRO_SYNC_TIMEOUT_SECONDS` | `15` | HTTP-Zeitlimit |
| `LIGAPRO_SYNC_MIN_FIXTURES` | `200` | minimale plausible Spielanzahl |
| `LIGAPRO_SYNC_MAX_FIXTURES` | `500` | maximale plausible Spielanzahl |
| `LIGAPRO_SYNC_LIVE_SECONDS` | `120` | Intervall rund um laufende Spiele |
| `LIGAPRO_SYNC_IDLE_SECONDS` | `21600` | maximales Leerlaufintervall |
| `LIGAPRO_SYNC_WINDOW_BEFORE_MINUTES` | `30` | Beginn des Live-Intervalls vor Anstoß |
| `LIGAPRO_SYNC_WINDOW_AFTER_MINUTES` | `300` | Ende des Live-Intervalls nach Anstoß |

Auf der Seite `Fecha actual` wird bei laufenden Spielen einmal pro
Minute neu geladen. Der Worker ist weiterhin nur einmal zu starten,
damit Abgleich, Tipperinnerungen und Standing-Jobs nicht mehrfach
parallel ausgeführt werden.

## Betriebskontrolle und Rückfallweg

Nach Aktivierung werden mindestens folgende Punkte beobachtet:

- Worker-Log meldet keine wiederkehrenden Synchronisationsfehler;
- alle lokalen Partien besitzen eine eindeutige externe ID;
- Anstoßzeiten werden mit der LigaPro-Seite stichprobenartig verglichen;
- während eines Testspiels erscheint `EN VIVO` in `Fecha actual`;
- der Live-Zwischenstand verändert nicht die Gesamtwertung;
- nach `Played` werden Endpunkte und Tabellen automatisch aktualisiert.

Bei Problemen wird `LIGAPRO_SYNC_ENABLED=0` gesetzt und der Worker neu
gestartet. Die Tippabgabe und die manuelle Ergebniseingabe funktionieren
weiter. Vor einem größeren Datenimport wird ein Datenbank-Backup
erstellt; falsche Endergebnisse werden erst nach Ursachenprüfung im
Adminbereich korrigiert.
