from django.core.management.base import BaseCommand

from tipping.tip_reminders import (
    send_due_tip_reminders,
)


class Command(BaseCommand):
    help = (
        "Versendet fällige Tipperinnerungen "
        "an Nutzer mit aktivierter Option."
    )

    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Zeigt Zähler an, ohne E-Mails zu "
                "versenden oder Zustellungen zu speichern."
            ),
        )

    def handle(self, *args, **options):
        result = send_due_tip_reminders(
            dry_run=options["dry_run"],
        )

        if not result.enabled and not result.dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "Tipperinnerungen sind global deaktiviert."
                )
            )
            return

        mode = (
            "Testlauf"
            if result.dry_run
            else "Versand"
        )
        self.stdout.write(
            (
                f"{mode} beendet: "
                f"{result.candidate_matches} Spiele im Fenster, "
                f"{result.due_deliveries} offene Tipps, "
                f"{result.recipients} Empfänger, "
                f"{result.deliveries_created} protokolliert, "
                f"{result.users_without_verified_email} ohne "
                f"bestätigte E-Mail, "
                f"{result.failures} Fehler."
            )
        )
