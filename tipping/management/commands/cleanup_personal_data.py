from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from tipping.data_retention import PersonalDataRetention


class Command(BaseCommand):
    help = (
        "Prüft Aufbewahrungsfristen und löscht freigegebene "
        "Altdaten nur mit --execute."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help=(
                "Führt die angezeigten Löschungen wirklich aus. "
                "Ohne diese Option bleibt der Befehl im Prüfmodus."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help=(
                "Maximale Zahl gelöschter Datensätze je Kategorie "
                "und Lauf. Standard: 500."
            ),
        )

    def handle(self, *args, **options):
        limit = options["limit"]

        if limit < 1:
            raise CommandError(
                "--limit muss mindestens 1 sein."
            )

        retention = PersonalDataRetention(
            limit=limit,
        )
        snapshot = retention.snapshot()

        self.stdout.write(
            "Datenaufbewahrung – Kandidaten:"
        )
        self.stdout.write(
            f"  Abgelaufene Sitzungen: "
            f"{snapshot.expired_sessions}"
        )
        self.stdout.write(
            f"  Abgelaufene E-Mail-Bestätigungen: "
            f"{snapshot.expired_email_confirmations}"
        )
        self.stdout.write(
            f"  Alte Erinnerungsnachweise: "
            f"{snapshot.old_reminder_deliveries}"
        )
        self.stdout.write(
            f"  Alte inaktive Mitgliedschaften: "
            f"{snapshot.old_inactive_memberships}"
        )
        self.stdout.write(
            f"  Alte unbestätigte Konten: "
            f"{snapshot.old_unverified_accounts}"
        )
        self.stdout.write(
            f"  Geschützte unbestätigte Konten: "
            f"{snapshot.protected_unverified_accounts}"
        )
        self.stdout.write(
            f"  Inaktive bestätigte Konten (nur Meldung): "
            f"{snapshot.inactive_accounts_for_notice}"
        )
        self.stdout.write(
            f"  Davon Gruppenbesitzer (nur Meldung): "
            f"{snapshot.inactive_group_owners_for_notice}"
        )

        if not options["execute"]:
            self.stdout.write(
                self.style.WARNING(
                    "Prüfmodus: Es wurden keine Daten gelöscht. "
                    "Zum Ausführen --execute ergänzen."
                )
            )
            return

        result = retention.execute()

        self.stdout.write(
            self.style.SUCCESS(
                "Bereinigung abgeschlossen "
                f"(maximal {limit} je Kategorie):"
            )
        )
        self.stdout.write(
            f"  Sitzungen gelöscht: {result.expired_sessions}"
        )
        self.stdout.write(
            "  E-Mail-Bestätigungen gelöscht: "
            f"{result.expired_email_confirmations}"
        )
        self.stdout.write(
            "  Erinnerungsnachweise gelöscht: "
            f"{result.old_reminder_deliveries}"
        )
        self.stdout.write(
            "  Inaktive Mitgliedschaften gelöscht: "
            f"{result.old_inactive_memberships}"
        )
        self.stdout.write(
            "  Unbestätigte Konten gelöscht: "
            f"{result.old_unverified_accounts}"
        )
        self.stdout.write(
            f"  Gruppen neu berechnet: {result.rebuilt_groups}"
        )
        self.stdout.write(
            self.style.WARNING(
                "Bestätigte inaktive Konten wurden nicht gelöscht; "
                "zuerst müssen Warnungen 30 und 7 Tage vorher "
                "umgesetzt werden."
            )
        )
