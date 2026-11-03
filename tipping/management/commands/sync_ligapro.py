from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from tipping.ligapro_sync import (
    LigaProFeedError,
    sync_ligapro_matches,
)


class Command(BaseCommand):
    help = (
        "Synchronisiert LigaPro-Anstoßzeiten, Live-Spielstände "
        "und Endergebnisse. Ohne --apply nur Prüfmodus."
    )

    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Schreibt die geprüften Änderungen in die Datenbank."
            ),
        )

    def handle(self, *args, **options):
        apply = options["apply"]

        try:
            result = sync_ligapro_matches(
                apply=apply,
            )

        except LigaProFeedError as exc:
            raise CommandError(str(exc)) from exc

        mode = "ANWENDEN" if apply else "PRÜFMODUS"
        self.stdout.write(f"LigaPro-Synchronisation: {mode}")
        self.stdout.write(
            f"Geladen: {result.fetched}, "
            f"zugeordnet: {result.matched}, "
            f"neu verknüpft: {result.linked}."
        )
        self.stdout.write(
            f"Geänderte Spiele: {result.changed}, "
            f"Anstoßzeiten: {result.kickoff_updates}, "
            f"Live-Spielstände: {result.live_updates}, "
            f"Endergebnisse: {result.final_updates}."
        )

        for label, values in (
            ("Nicht zugeordnet", result.unmatched),
            ("Mehrdeutig", result.ambiguous),
            ("Konflikte", result.conflicts),
        ):
            if not values:
                continue

            self.stderr.write(
                self.style.WARNING(
                    f"{label}: {len(values)}"
                )
            )

            for value in values[:10]:
                self.stderr.write(f"- {value}")

            if len(values) > 10:
                self.stderr.write(
                    f"- … {len(values) - 10} weitere"
                )

        if result.skipped:
            raise CommandError(
                "Nicht alle Spiele konnten sicher synchronisiert werden. "
                "Es wurden keine Änderungen gespeichert."
            )

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "Prüfmodus: Es wurde nichts gespeichert. "
                    "Zum Übernehmen erneut mit --apply ausführen."
                )
            )

        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "LigaPro-Daten erfolgreich synchronisiert."
                )
            )
