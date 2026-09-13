# Release-Abnahme für Puntero

Diese Checkliste trennt die reproduzierbare technische Prüfung von der
manuellen Produktabnahme. Beide Teile müssen für denselben Commit
erfolgreich sein, bevor dieser als Release-Kandidat gilt.

## 1. Automatisierte Abnahme

Im Projektverzeichnis ausführen:

```sh
bin/check_acceptance.sh
```

Das Skript verwendet eine neu angelegte temporäre SQLite-Datenbank und
das speicherinterne E-Mail-Backend. Es liest weder die lokale
`db.sqlite3` noch Railway-Daten und versendet keine E-Mails. Nach dem
Lauf wird das temporäre Verzeichnis entfernt.

Geprüft werden in einem zusammenhängenden Szenario:

- Healthcheck und deaktivierte Rechtstext-Seiten;
- Registrierung mit verpflichtender 18+-Bestätigung;
- Erzeugung einer Bestätigungs-E-Mail ohne externen Versand;
- Anmeldung über E-Mail-Adresse und Benutzername;
- Erstellung einer Gruppe und ihrer Eigentümermitgliedschaft;
- Beitritt über einen nicht normalisierten Einladungscode;
- Tippabgabe durch zwei Mitglieder;
- manuelle Ergebniseingabe und anschließende Punkteberechnung;
- Rang, Spieltagssieg, Spieltagstabelle und Gesamttabelle;
- freiwillige Aktivierung der Tipperinnerung.

Anschließend muss zusätzlich der vollständige Release-Check laufen:

```sh
bin/check_release.sh
```

## 2. Manuelle lokale Produktabnahme

Die manuelle Kontrolle erfolgt mit Testkonten und ohne persönliche
Echtdaten. Der Browser sollte einmal in einer schmalen Mobilansicht und
einmal auf einem Desktop geprüft werden.

### Registrierung und Konto

- [ ] Registrierung ohne 18+-Bestätigung wird verständlich abgewiesen.
- [ ] Registrierung mit Bestätigung erzeugt genau eine E-Mail.
- [ ] Der Bestätigungslink funktioniert nur einmal.
- [ ] Anmeldung funktioniert mit Benutzername und E-Mail-Adresse.
- [ ] Passwort-Reset funktioniert vollständig.
- [ ] Falsche Zugangsdaten verraten nicht, ob eine E-Mail existiert.
- [ ] Tipperinnerungen sind zunächst deaktiviert und frei wählbar.
- [ ] Eine Kontolöschung verlangt Passwort und `ELIMINAR`.

### Gruppen

- [ ] Ein Nutzer kann eine Gruppe erstellen und den Code kopieren.
- [ ] Ein zweiter Nutzer kann über Code oder Einladungslink beitreten.
- [ ] Geschlossene Gruppen weisen neue Mitglieder verständlich ab.
- [ ] Nur der Eigentümer kann Namen, Beitritt und Mitglieder verwalten.
- [ ] Entfernen, Wiedereintritt, Eigentumsübertragung und Löschen sind geprüft.
- [ ] E-Mail-Adressen anderer Mitglieder werden nirgends angezeigt.

### Tipps und Ergebnisse

- [ ] Tipps lassen sich bis zum Anstoß speichern und ändern.
- [ ] Ab Anstoß sind Tipps gesperrt und für die Gruppe sichtbar.
- [ ] Ungültige oder unvollständige Werte werden sicher behandelt.
- [ ] Ein manuell eingetragenes Ergebnis aktualisiert Punkte und Tabellen.
- [ ] Eine Ergebniskorrektur berechnet alle betroffenen Werte neu.
- [ ] Gleiche Punktzahl und gleiche Spieltagssiege ergeben denselben Rang.
- [ ] Spieltagssiege entscheiden die Reihenfolge bei gleicher Punktzahl.
- [ ] Bonuspunkte erscheinen erst zum vorgesehenen Zeitpunkt.

### Darstellung und Betrieb

- [ ] Öffentliche Startseite und Hilfe sind ohne Anmeldung erreichbar.
- [ ] Dashboard, Tippseite und beide Tabellen sind mobil bedienbar.
- [ ] Navigation, Dialoge und Fehlermeldungen sind verständlich.
- [ ] `/health/` antwortet erfolgreich.
- [ ] Rechtstext-URLs antworten bei `LEGAL_PAGES_ENABLED=0` mit 404.
- [ ] Bei lokaler Vorschau sind Platzhalter und „No publicar“ sichtbar.
- [ ] Es befinden sich keine Zugangsdaten oder Echtdaten im Git-Diff.

## 3. Ergebnis dokumentieren

Für die Freigabe werden festgehalten:

- Commit-ID:
- Datum und Zeitzone:
- prüfende Person:
- Ergebnis `check_acceptance.sh`:
- Ergebnis `check_release.sh`:
- getesteter Browser und Mobilbreite:
- offene Abweichungen mit Entscheidung:

Ein fehlgeschlagener Pflichtpunkt wird entweder vor dem Release behoben
oder ausdrücklich mit Risiko, Verantwortlichem und Folgetermin
dokumentiert.
