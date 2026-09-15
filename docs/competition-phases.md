# LigaPro-Wettbewerbsphasen

Puntero führt die reguläre Saison und die Finalphasen als ein gemeinsames
Turnier. Dadurch bleiben Gruppen, Tipps, Gesamtpunkte, Spieltagssiege und
Bonustipps über die komplette Saison erhalten.

## Standardphasen

Für jedes neue Turnier werden automatisch vier Phasen angelegt:

| Code | Anzeigename | Runden |
|---|---|---:|
| `regular` | Fase regular | 30 |
| `hexagonal_final` | Hexagonal final | 10 |
| `cuadrangular` | Cuadrangular | 6 |
| `hexagonal_descenso` | Hexagonal de descenso | 10 |

`Match.matchday` bleibt die globale Spieltagsnummer. Die reguläre Saison
verwendet 1 bis 30. Die gemeinsamen Finaltermine verwenden 31 bis 40.
`Match.stage_round` beginnt innerhalb der Finalphasen erneut bei 1.

Beispiel: Ein Spiel des Hexagonal final in der ersten Finalrunde erhält
`matchday=31`, `stage=Hexagonal final` und `stage_round=1`. Spiele des
Cuadrangular und des Hexagonal de descenso am gleichen Finaltermin erhalten
ebenfalls `matchday=31` und `stage_round=1`.

Die Punkteberechnung fasst alle Spiele mit derselben globalen
Spieltagsnummer zusammen. Damit entsteht für Runde 1 der drei Finalphasen
genau eine gemeinsame Spieltagswertung.

## Pflege im Django-Admin

Unter **Turnierphasen** lassen sich Anzeigename, Reihenfolge und Rundenzahl
kontrollieren. Bei einem Spiel werden zusätzlich zur globalen Fecha die
Phase und die Phasenrunde ausgewählt. Eine Phase aus einem anderen Turnier
oder eine zu hohe Phasenrunde wird beim Speichern abgewiesen.

Bestehende Spiele werden bei der Migration automatisch der `Fase regular`
zugeordnet. Ihre bisherige globale Fecha wird dabei als Phasenrunde
übernommen.

## CSV-Import

Der Befehl `import_matches` erkennt zusätzlich diese optionalen Spalten:

- `phase` oder `Fase`: Phasencode oder spanischer Anzeigename;
- `stage_round` oder `Fecha de fase`: Runde innerhalb der Phase.

Ohne Phase werden Spiele mit vorhandener Fecha der regulären Saison
zugeordnet. Bei einer Finalphase kann die Phasenrunde aus einer globalen
Fecha ab 31 abgeleitet werden; eine explizite Angabe ist dennoch vorzuziehen.
