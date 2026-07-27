from django.core.management.base import (
    BaseCommand,
)
from django.db.models import Q

from tipping.models import Match, Prediction
from tipping.scoring import (
    recalculate_points_for_match,
)


class Command(BaseCommand):
    help = (
        "Berechnet die Punkte aller vorhandenen "
        "Tipps für beendete Spiele neu."
    )

    def handle(self, *args, **options):
        self.stdout.write(
            "Lösche Punkte von Spielen ohne "
            "vollständiges Ergebnis ..."
        )

        cleared_count = (
            Prediction.objects
            .filter(
                Q(
                    match__home_score__isnull=True,
                )
                | Q(
                    match__away_score__isnull=True,
                )
            )
            .exclude(
                points__isnull=True,
            )
            .update(
                points=None,
            )
        )

        self.stdout.write(
            f"{cleared_count} ungültige Punktwerte gelöscht."
        )

        finished_matches = (
            Match.objects
            .filter(
                home_score__isnull=False,
                away_score__isnull=False,
            )
            .order_by("id")
        )

        match_count = finished_matches.count()
        updated_predictions = 0

        self.stdout.write(
            f"{match_count} beendete Spiele gefunden."
        )

        for index, match in enumerate(
            finished_matches.iterator(
                chunk_size=100
            ),
            start=1,
        ):
            updated_predictions += (
                recalculate_points_for_match(
                    match
                )
            )

            if index % 25 == 0:
                self.stdout.write(
                    f"{index} von {match_count} "
                    "Spielen verarbeitet ..."
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Fertig: {updated_predictions} "
                "Tipps wurden neu bewertet."
            )
        )