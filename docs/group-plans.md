# Gruppenpläne: Free, Plus und Club

## Aktueller Status

Die Anwendung besitzt eine deaktivierbare technische Grundlage für
Gruppenpläne. Der private Testlauf bleibt unverändert kostenlos:

- Es gibt keinen Checkout und keine Zahlungsabwicklung.
- Neue Gruppen starten immer mit `Free`.
- `Plus` und `Club` können ausschließlich im Django-Admin testweise
  und optional mit einem Ablaufdatum vergeben werden.
- Abgelaufene Freigaben erhalten automatisch die Free-Berechtigungen.
- Die Teilnehmergrenzen werden erst mit einem separaten Schalter
  durchgesetzt.

Der Tarif gehört zur Gruppe. Teilnehmer benötigen kein persönliches
Abonnement und können weiterhin kostenlos spielen.

## Konfiguration

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `GROUP_PLANS_ENABLED` | `0` | Zeigt `/planes/`, Menülinks und Plan-Badges an. |
| `GROUP_PLAN_LIMITS_ENABLED` | `0` | Verhindert neue Beitritte, sobald das Plan-Limit erreicht ist. |
| `GROUP_PLAN_FREE_MEMBER_LIMIT` | `20` | Vorgeschlagene maximale Gruppengröße für Free. |
| `GROUP_PLAN_PLUS_MEMBER_LIMIT` | `100` | Vorgeschlagene maximale Gruppengröße für Plus. |
| `GROUP_PLAN_PLUS_PRICE_USD` | `12` | Unverbindlicher Jahrespreis der Vorschau. |
| `GROUP_PLAN_CLUB_PRICE_USD` | `99` | Unverbindlicher Einstiegspreis pro Turnier. |

`GROUP_PLAN_LIMITS_ENABLED=1` setzt `GROUP_PLANS_ENABLED=1` voraus.
In Produktion kann die Tarifvorschau außerdem nur gemeinsam mit
vollständigen und bestätigten Rechtstexten aktiviert werden.

Für eine lokale Vorschau genügt:

```sh
GROUP_PLANS_ENABLED=1
GROUP_PLAN_LIMITS_ENABLED=0
```

Danach ist die Seite unter `http://127.0.0.1:8000/planes/` erreichbar.

## Verhalten der Teilnehmerlimits

Solange `GROUP_PLAN_LIMITS_ENABLED=0` ist, verändern die Pläne keinen
Nutzerablauf. Nach der Aktivierung gelten die konfigurierten Limits für
neue und zurückkehrende Mitglieder:

- Free: konfiguriertes Free-Limit
- Plus: konfiguriertes Plus-Limit
- Club: kein Teilnehmerlimit

Bereits aktive Mitglieder werden nicht entfernt. Der Gruppeninhaber ist
Teil des Limits. Dadurch erfolgt eine Einführung ohne Datenverlust.

## Coadministratoren

Gruppen mit einem wirksamen `Plus`- oder `Club`-Plan können bereits
Coadministratoren einsetzen. Der Gruppeninhaber weist die Rolle auf der
Detailseite der Gruppe zu und kann sie dort wieder entziehen.

Coadministratoren dürfen:

- den Gruppennamen und den Beitrittsstatus ändern,
- den Einladungscode erneuern,
- reguläre Teilnehmer aus der Gruppe entfernen.

Nur der Gruppeninhaber darf Coadministratoren ernennen oder abberufen,
andere Coadministratoren entfernen, das Eigentum übertragen und die
Gruppe löschen. Ergebnisse werden weiterhin zentral im Django-Admin
erfasst und gehören nicht zu dieser Rolle.

Wird ein Plus- oder Club-Plan unwirksam, bleiben die Zuweisungen in der
Datenbank erhalten, verleihen jedoch keine Verwaltungsrechte. Dadurch
werden sie nach einer erneuten Freigabe automatisch wieder aktiv. Beim
Entfernen eines Mitglieds wird dessen Coadministrator-Rolle gelöscht.

## Erweiterte Gruppenstatistiken

Mitglieder einer Gruppe mit wirksamem `Plus`- oder `Club`-Plan können
unter `/groups/<gruppen-id>/estadisticas/` folgende Auswertungen öffnen:

- `Resumen`: kompakter Gruppenbericht mit den wichtigsten Kennzahlen,
  Rang, Punkten, letzten fünf Spieltagen, Trefferquote und Anzahl der
  Führungswechsel,
- `Comparar`: direkter Vergleich und kumulierter Punkte- und Rangverlauf
  zweier frei wählbarer Teilnehmer,
- `Participación`: Teilnahmequote je Person und begonnenem Spieltag.

Die Verlaufsdiagramme basieren auf den vorberechneten Spieltagstabellen
und zeigen deshalb ausschließlich Spielpunkte. Sobald Bonuspunkte in der
Gesamtwertung sichtbar sind, berücksichtigt der Gruppenbericht sie in
Punktzahl und Rang und kennzeichnet den Unterschied.

Für Teilnahmequoten werden nur Spiele berücksichtigt, die bereits
begonnen haben und nach dem Beitritt des jeweiligen Mitglieds lagen.
Ein vorhandener früherer Tipp wird auch nach einem Wiedereintritt
berücksichtigt. Weder Tippwerte noch E-Mail-Adressen werden für die
Auswertung an die Seite übergeben. Free-Gruppen und abgelaufene
Freigaben erhalten auf dem Endpunkt eine 404-Antwort.

## Was vor echten Zahlungen noch fehlt

Die aktuelle Umsetzung ist absichtlich keine Abonnementverwaltung. Für
den kommerziellen Betrieb sind mindestens folgende Erweiterungen nötig:

1. Preise und enthaltene Funktionen mit Testnutzern validieren.
2. Die übrigen als „vorgesehen“ markierten Plus- und Club-Funktionen
   tatsächlich implementieren und über die zentrale
   Berechtigungsprüfung freigeben.
3. Einen in Ecuador geeigneten Zahlungsanbieter auswählen und Checkout,
   Verlängerung, Kündigung, Rückerstattung und Rechnungsdaten definieren.
4. Separate Zahlungs- und Abonnementmodelle mit Provider-IDs,
   Periodenstatus und einer unveränderbaren Ereignishistorie ergänzen.
5. Signierte Webhooks idempotent verarbeiten; ein Browser-Redirect darf
   niemals allein einen bezahlten Plan freischalten.
6. Kulanzfrist, fehlgeschlagene Zahlungen, Herabstufung und den Umgang
   mit Gruppen oberhalb des neuen Limits festlegen.
7. Datenschutz, Nutzungsbedingungen, Kontaktangaben, Steuerfragen und
   Verbraucherinformationen fachlich sowie juristisch finalisieren.
8. Erst danach Kaufbuttons, E-Mails und produktive Limits aktivieren.

## Empfohlene Einführung

1. Privater Test: beide Schalter bleiben `0`.
2. Produktvorschau: nur `GROUP_PLANS_ENABLED=1`; Feedback zu Preis und
   Funktionsumfang sammeln.
3. Interner Limit-Test: beide Schalter ausschließlich in einer
   Testumgebung aktivieren.
4. Kommerzieller Pilot: Zahlungs- und Rechtsstrecke vollständig testen,
   danach zunächst wenige Plus-Gruppen freischalten.
