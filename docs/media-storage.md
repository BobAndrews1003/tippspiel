# Dauerhafte Speicherung von Logos und Titelbildern

Gruppenlogos und Titelbilder dürfen in Produktion nicht im Dateisystem
des Web-Containers liegen. Ein neues Deployment kann diesen Speicher
ersetzen. Puntero verwendet deshalb in Railway einen privaten,
S3-kompatiblen Bucket. Lokal bleibt standardmäßig das nicht versionierte
`media/`-Verzeichnis aktiv.

Die Anwendung erzeugt für private Objekte zeitlich begrenzte, signierte
URLs. Der Bucket muss nicht öffentlich gemacht werden. Das eingestellte
Speicher-Backend gilt ausschließlich für Benutzer-Uploads; statische
Dateien werden weiterhin mit WhiteNoise ausgeliefert.

## Railway-Bucket einrichten

1. Im Railway-Projekt über `Create` einen `Bucket` in derselben Region
   wie der Webservice anlegen, zum Beispiel mit dem Anzeigenamen
   `puntero-media`.
2. Im Bucket unter `Credentials` prüfen, ob `Virtual-hosted-style` oder
   `Path-style` angegeben ist. Neue Buckets verwenden in der Regel
   `Virtual-hosted-style`.
3. Im **Webservice** folgende Variablen als Railway-Referenzen auf die
   Bucket-Variablen anlegen. `Bucket` im Beispiel ist der tatsächliche
   Name des Bucket-Service:

   | Puntero-Variable | Railway-Wert |
   | --- | --- |
   | `MEDIA_STORAGE_BACKEND` | `s3` |
   | `MEDIA_S3_BUCKET_NAME` | `${{Bucket.BUCKET}}` |
   | `MEDIA_S3_ACCESS_KEY_ID` | `${{Bucket.ACCESS_KEY_ID}}` |
   | `MEDIA_S3_SECRET_ACCESS_KEY` | `${{Bucket.SECRET_ACCESS_KEY}}` |
   | `MEDIA_S3_REGION_NAME` | `${{Bucket.REGION}}` |
   | `MEDIA_S3_ENDPOINT_URL` | `${{Bucket.ENDPOINT}}` |
   | `MEDIA_S3_ADDRESSING_STYLE` | `virtual` oder laut Credentials `path` |
   | `MEDIA_S3_QUERYSTRING_EXPIRE` | `3600` |

   Für `MEDIA_S3_BUCKET_NAME` muss `BUCKET` verwendet werden, nicht
   `RAILWAY_BUCKET_NAME`. Die Referenzen vermeiden kopierte
   Zugangsdaten und übernehmen die Werte der jeweiligen Railway-Umgebung.
4. Den Webservice neu deployen. Der Standing-Worker benötigt die
   Bucket-Zugangsdaten derzeit nicht, weil er keine Bilder verarbeitet.

Echte Zugangsdaten werden niemals in `.env`, `.env.example`, Commits,
Logs oder Tickets übernommen.

## Verbindung prüfen

Nach dem Deployment einmal in einer Railway-Shell des Webservice
ausführen:

```sh
python manage.py check_media_storage
```

Der Befehl schreibt eine zufällig benannte Testdatei, liest sie zurück
und löscht sie sofort wieder. Er gibt keine Zugangsdaten aus. Erst wenn
alle drei Schritte erfolgreich sind, werden über den Django-Admin oder
die Gruppenverwaltung ein Testlogo und ein Test-Titelbild hochgeladen.

Danach kontrollieren:

- beide Bilder erscheinen nach einem vollständigen Neuladen der Seite;
- die Bilder bleiben nach einem erneuten Deployment erhalten;
- ihre Browser-URLs enthalten eine Signatur und laufen nach der
  konfigurierten Zeit ab;
- das Ersetzen oder Zurücksetzen eines Bildes entfernt die alte Datei
  aus dem Bucket;
- Bildformat, Dateigröße und Abmessungen werden weiterhin abgewiesen,
  wenn sie die Anwendungsgrenzen überschreiten.

## Sicherheit und Betrieb

Der Bucket bleibt privat. Puntero verwendet keine öffentlichen ACLs,
überschreibt keine bestehenden Dateinamen und setzt für gelieferte
Objekte einen privaten Cache-Hinweis. Die Content-Security-Policy wird
automatisch um genau den konfigurierten Bucket-Ursprung erweitert.

Railway-Buckets bieten derzeit keine automatischen Backups,
Objektversionierung oder Lifecycle-Regeln. Wichtige Originaldateien
müssen deshalb zusätzlich außerhalb des Buckets gesichert werden. Das
Löschen eines Buckets ist nach Railways aktueller Dokumentation nur 52
Stunden wiederherstellbar.

Der Speicher ist für die kleinen Puntero-Bilder sehr günstig: Railway
berechnet derzeit 0,015 US-Dollar pro GB und Monat; API-Operationen und
Bucket-Egress sind kostenlos. Die Konfiguration verwendet bewusst den
allgemeinen S3-Standard. Falls später Cloudflare R2 eingesetzt werden
soll, können Bucket, Schlüssel, Region, Endpoint und gegebenenfalls der
Adressierungsstil ausgetauscht werden, ohne die Bildmodelle zu ändern.

## Referenzen

- [Railway: Storage Buckets](https://docs.railway.com/storage-buckets)
- [django-storages: S3](https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html)
- [Cloudflare R2: Preise](https://developers.cloudflare.com/r2/pricing/)
