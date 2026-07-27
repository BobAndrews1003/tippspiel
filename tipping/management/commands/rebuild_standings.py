from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.db import transaction

from tipping.models import (
    Group,
    Match,
    MatchdayScore,
)
from tipping.standings import (
    rebuild_group_standing,
    rebuild_group_timeline,
    rebuild_matchday_scores,
)


class Command(BaseCommand):
    help = (
        "Berechnet MatchdayScore, historische Ränge "
        "und GroupStanding vollständig neu."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--group-id",
            type=int,
            help=(
                "Optional: Nur diese Gruppe "
                "neu berechnen."
            ),
        )

    def handle(self, *args, **options):
        group_id = options.get("group_id")

        groups = (
            Group.objects
            .select_related("tournament")
            .order_by("id")
        )

        if group_id is not None:
            groups = groups.filter(
                pk=group_id,
            )

            if not groups.exists():
                raise CommandError(
                    f"Gruppe {group_id} existiert nicht."
                )

        processed_groups = 0
        total_matchday_rows = 0
        total_timeline_rows = 0
        total_standing_rows = 0
        total_stale_rows = 0

        for group in groups.iterator(
            chunk_size=100,
        ):
            result_matchdays = list(
                Match.objects
                .filter(
                    tournament_id=(
                        group.tournament_id
                    ),
                    matchday__isnull=False,
                    home_score__isnull=False,
                    away_score__isnull=False,
                )
                .values_list(
                    "matchday",
                    flat=True,
                )
                .distinct()
                .order_by("matchday")
            )

            with transaction.atomic():
                # Entfernt vorberechnete Zeilen für
                # Spieltage, die aktuell keine Ergebnisse
                # mehr besitzen.
                stale_scores = (
                    MatchdayScore.objects
                    .filter(
                        group_id=group.id,
                    )
                )

                if result_matchdays:
                    stale_scores = (
                        stale_scores.exclude(
                            matchday__in=(
                                result_matchdays
                            ),
                        )
                    )

                deleted_rows, _ = (
                    stale_scores.delete()
                )

                matchday_rows = 0

                for matchday in result_matchdays:
                    matchday_rows += (
                        rebuild_matchday_scores(
                            group_id=group.id,
                            matchday=matchday,
                        )
                    )

                if result_matchdays:
                    timeline_rows = (
                        rebuild_group_timeline(
                            group_id=group.id,
                        )
                    )
                else:
                    timeline_rows = 0

                standing_rows = (
                    rebuild_group_standing(
                        group_id=group.id,
                    )
                )

            processed_groups += 1
            total_matchday_rows += matchday_rows
            total_timeline_rows += timeline_rows
            total_standing_rows += standing_rows
            total_stale_rows += deleted_rows

            self.stdout.write(
                (
                    f"Gruppe {group.id} "
                    f"«{group.name}»: "
                    f"{len(result_matchdays)} Spieltage, "
                    f"{matchday_rows} Spieltagssummen, "
                    f"{timeline_rows} Timeline-Zeilen, "
                    f"{standing_rows} Ranglistenzeilen, "
                    f"{deleted_rows} alte Zeilen entfernt."
                )
            )

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Rebuild abgeschlossen: "
                    f"{processed_groups} Gruppen, "
                    f"{total_matchday_rows} "
                    "Spieltagssummen, "
                    f"{total_timeline_rows} "
                    "Timeline-Zeilen, "
                    f"{total_standing_rows} "
                    "Ranglistenzeilen, "
                    f"{total_stale_rows} "
                    "alte Zeilen entfernt."
                )
            )
        )
