# Wettbewerbe der Saison 2027

Puntero kann pro Tippgruppe mehrere offizielle Wettbewerbe derselben
Saison kombinieren. Die Gesamtwertung addiert die Punkte aus allen von
der Gruppe ausgewählten Wettbewerben. Spieltage mit derselben Nummer
bleiben technisch getrennt.

## Einrichtung im Admin

Die drei leeren Wettbewerbe können zunächst verborgen angelegt werden:

```bash
python manage.py bootstrap_2027_competitions
```

Für einen lokalen Test können sie sofort freigeschaltet werden:

```bash
python manage.py bootstrap_2027_competitions --open-for-groups
```

Alternativ erfolgt die Einrichtung vollständig im Admin:

1. Unter **Saisons** `Temporada 2027` mit dem Jahr `2027` anlegen.
2. Unter **Turniere** die gewünschten Wettbewerbe anlegen:

   - `LigaPro 2027`, Code `ligapro`
   - `Copa Ecuador 2027`, Code `copa-ecuador`
   - `Copa de la Liga 2027`, Code `copa-de-la-liga`

3. Alle drei Turniere der Saison `Temporada 2027` zuordnen.
4. `Auswählbar` erst aktivieren, wenn der Wettbewerb für neue Gruppen
   angeboten werden soll. So kann insbesondere die Copa de la Liga bis
   zur endgültigen Bestätigung verborgen bleiben.
5. Phasen und Rundenzahlen je Wettbewerb im Turnier-Admin konfigurieren.
6. Spiele wie bisher importieren; jedes Spiel gehört weiterhin genau
   einem Turnier.

## Verhalten für Gruppen

- Bei der Gruppenerstellung können ein oder mehrere Turniere derselben
  Saison ausgewählt werden.
- LigaPro wird, sofern ausgewählt, als primärer Wettbewerb verwendet.
- Bonustipps beziehen sich vorerst ausschließlich auf den primären
  Wettbewerb.
- Nach dem ersten vollständigen Tipp wird die Auswahl des betreffenden
  Wettbewerbs gesperrt.
- `Pronosticar`, `Fecha actual` und die Spieltagsspalten lassen sich über
  einen Wettbewerbsumschalter wechseln.
- Die Gesamtpunkte und Spieltagssiege werden über alle ausgewählten
  Wettbewerbe gemeinsam geführt.

## Bestehende Daten

Die Migration `0029_multi_tournament_groups` ordnet jede vorhandene
Gruppe automatisch ihrem bisherigen Turnier zu. Vorhandene Tipps,
Ergebnisse und Ranglisten bleiben erhalten. Bestehende
`MatchdayScore`-Zeilen erhalten den bisherigen Wettbewerb der Gruppe.
