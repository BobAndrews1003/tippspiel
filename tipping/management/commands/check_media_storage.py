from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import (
    BaseCommand,
    CommandError,
)


class Command(BaseCommand):
    help = (
        "Prüft den konfigurierten Medienspeicher durch "
        "Schreiben, Lesen und anschließendes Löschen einer Testdatei."
    )

    requires_system_checks = []

    def handle(self, *args, **options):
        payload = b"puntero-media-storage-check\n"
        requested_name = (
            "storage-checks/"
            f"check-{uuid4().hex}.txt"
        )
        saved_name = ""
        operation_error = None
        cleanup_error = None

        try:
            saved_name = default_storage.save(
                requested_name,
                ContentFile(payload),
            )

            if not default_storage.exists(saved_name):
                raise RuntimeError(
                    "Die Testdatei ist nach dem Schreiben nicht vorhanden."
                )

            with default_storage.open(
                saved_name,
                mode="rb",
            ) as stored_file:
                stored_payload = stored_file.read()

            if stored_payload != payload:
                raise RuntimeError(
                    "Der gelesene Inhalt stimmt nicht mit dem Testinhalt "
                    "überein."
                )

        except Exception as exc:
            operation_error = exc

        finally:
            if saved_name:
                try:
                    default_storage.delete(saved_name)
                    if default_storage.exists(saved_name):
                        raise RuntimeError(
                            "Die Testdatei ist nach dem Löschen noch "
                            "vorhanden."
                        )
                except Exception as exc:
                    cleanup_error = exc

        if operation_error is not None:
            cleanup_hint = (
                " Auch das Aufräumen der Testdatei ist "
                f"fehlgeschlagen: {cleanup_error}"
                if cleanup_error is not None
                else ""
            )
            raise CommandError(
                "Medienspeicher-Prüfung fehlgeschlagen: "
                f"{operation_error}.{cleanup_hint}"
            ) from operation_error

        if cleanup_error is not None:
            raise CommandError(
                "Medienspeicher-Prüfung konnte die Testdatei nicht "
                f"entfernen: {cleanup_error}"
            ) from cleanup_error

        self.stdout.write(
            self.style.SUCCESS(
                "Medienspeicher erfolgreich geprüft: "
                "Schreiben, Lesen und Löschen funktionieren."
            )
        )
