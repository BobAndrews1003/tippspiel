from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from tipping.account_retention_notices import (
    send_due_account_retention_notices,
)


class Command(BaseCommand):
    help = (
        "Prüft Warnungen vor der Löschung inaktiver Konten. "
        "Versand nur mit --execute und aktiviertem Schalter."
    )

    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help=(
                "Versendet fällige Warnungen. Ohne diese Option "
                "bleibt der Befehl im Prüfmodus."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help=(
                "Maximale Zahl der Warnungen in diesem Lauf. "
                "Standard: ACCOUNT_RETENTION_NOTICE_BATCH_SIZE."
            ),
        )

    def handle(self, *args, **options):
        limit = options["limit"]

        if limit is not None and limit < 1:
            raise CommandError(
                "--limit muss mindestens 1 sein."
            )

        execute = options["execute"]
        result = send_due_account_retention_notices(
            dry_run=not execute,
            limit=limit,
        )

        if execute and not result.enabled:
            self.stdout.write(
                self.style.WARNING(
                    "Kontowarnungen sind global deaktiviert. "
                    "Es wurden keine E-Mails versendet."
                )
            )
            return

        mode = "Versand" if execute else "Prüfmodus"
        self.stdout.write(
            (
                f"{mode} beendet: "
                f"{result.first_due} erste Warnungen, "
                f"{result.final_due} letzte Warnungen, "
                f"{result.sent} versendet, "
                f"{result.users_without_verified_email} ohne "
                f"bestätigte E-Mail, "
                f"{result.failures} Fehler."
            )
        )

        if not execute:
            self.stdout.write(
                self.style.WARNING(
                    "Es wurden keine E-Mails versendet. Für den "
                    "Versand --execute ergänzen und den globalen "
                    "Schalter aktivieren."
                )
            )
