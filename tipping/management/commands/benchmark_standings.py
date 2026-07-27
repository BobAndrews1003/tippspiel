from datetime import timedelta
from time import perf_counter
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.db import connection, transaction
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
)
from tipping.result_processing import (
    process_match_change,
)
from tipping.standings import (
    rebuild_group_bonus_points,
    rebuild_group_timeline,
    rebuild_matchday_scores,
)


class Command(BaseCommand):
    help = (
        "Misst die Laufzeit der Ranglisten-Rebuilds "
        "mit temporären Testdaten. Alle erzeugten Daten "
        "werden am Ende zurückgerollt."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--users",
            type=int,
            default=500,
            help=(
                "Teilnehmer pro Gruppe. "
                "Standard: 500."
            ),
        )

        parser.add_argument(
            "--groups",
            type=int,
            default=3,
            help=(
                "Anzahl der Gruppen. "
                "Standard: 3."
            ),
        )

        parser.add_argument(
            "--matchdays",
            type=int,
            default=34,
            help=(
                "Anzahl ausgewerteter Spieltage. "
                "Standard: 34."
            ),
        )

    def handle(self, *args, **options):
        user_count = options["users"]
        group_count = options["groups"]
        matchday_count = options[
            "matchdays"
        ]

        for name, value in (
            ("users", user_count),
            ("groups", group_count),
            (
                "matchdays",
                matchday_count,
            ),
        ):
            if value < 1:
                raise CommandError(
                    f"--{name} muss mindestens 1 sein."
                )

        prefix = (
            "benchmark-"
            + uuid4().hex[:10]
        )

        expected_predictions = (
            user_count
            * group_count
            * matchday_count
        )

        expected_matchday_scores = (
            user_count
            * group_count
            * matchday_count
        )

        expected_standings = (
            user_count
            * group_count
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "Lokaler Ranglisten-Benchmark"
            )
        )

        self.stdout.write(
            (
                f"Datenbank: "
                f"{connection.vendor}"
            )
        )

        self.stdout.write(
            (
                f"{user_count} Nutzer · "
                f"{group_count} Gruppen · "
                f"{matchday_count} Spieltage"
            )
        )

        self.stdout.write(
            (
                f"Erwartete Tipps: "
                f"{expected_predictions:,}"
            )
        )

        self.stdout.write("")

        with transaction.atomic():
            # --------------------------------------------------
            # Testdaten erzeugen
            # --------------------------------------------------

            seed_started = perf_counter()

            User = get_user_model()

            User.objects.bulk_create(
                [
                    User(
                        username=(
                            f"{prefix}-"
                            f"user-{index:04d}"
                        )
                    )
                    for index in range(
                        1,
                        user_count + 1,
                    )
                ],
                batch_size=1000,
            )

            users = list(
                User.objects
                .filter(
                    username__startswith=(
                        f"{prefix}-user-"
                    )
                )
                .order_by("username")
            )

            if len(users) != user_count:
                raise CommandError(
                    "Nicht alle Benchmark-Nutzer "
                    "wurden erzeugt."
                )

            tournament = (
                Tournament.objects.create(
                    name=(
                        f"{prefix}-tournament"
                    ),
                )
            )

            Group.objects.bulk_create(
                [
                    Group(
                        tournament=tournament,
                        name=(
                            f"{prefix}-"
                            f"group-{index:03d}"
                        ),
                        owner=users[0],
                    )
                    for index in range(
                        1,
                        group_count + 1,
                    )
                ],
                batch_size=100,
            )

            groups = list(
                Group.objects
                .filter(
                    tournament=tournament,
                )
                .order_by("id")
            )

            GroupMembership.objects.bulk_create(
                [
                    GroupMembership(
                        group=group,
                        user=user,
                        is_creator=(
                            user.id
                            == users[0].id
                        ),
                    )
                    for group in groups
                    for user in users
                ],
                batch_size=1000,
            )

            first_kickoff = (
                timezone.now()
                - timedelta(
                    days=matchday_count + 1,
                )
            )

            Match.objects.bulk_create(
                [
                    Match(
                        tournament=tournament,
                        home_team=(
                            f"Equipo Local "
                            f"{matchday}"
                        ),
                        away_team=(
                            f"Equipo Visitante "
                            f"{matchday}"
                        ),
                        kickoff=(
                            first_kickoff
                            + timedelta(
                                days=matchday,
                            )
                        ),
                        matchday=matchday,
                        home_score=2,
                        away_score=1,
                    )
                    for matchday in range(
                        1,
                        matchday_count + 1,
                    )
                ],
                batch_size=500,
            )

            matches = list(
                Match.objects
                .filter(
                    tournament=tournament,
                )
                .order_by("matchday")
            )

            for group in groups:
                Prediction.objects.bulk_create(
                    [
                        Prediction(
                            group=group,
                            user=user,
                            match=match,
                            pred_home=2,
                            pred_away=1,
                            points=4,
                        )
                        for match in matches
                        for user in users
                    ],
                    batch_size=1000,
                )

            seed_seconds = (
                perf_counter()
                - seed_started
            )

            actual_predictions = (
                Prediction.objects
                .filter(
                    group__tournament=(
                        tournament
                    ),
                )
                .count()
            )

            if (
                actual_predictions
                != expected_predictions
            ):
                raise CommandError(
                    "Unerwartete Zahl an Tipps: "
                    f"{actual_predictions} statt "
                    f"{expected_predictions}."
                )

            # --------------------------------------------------
            # Vollständigen Rebuild messen
            # --------------------------------------------------

            full_rebuild_started = (
                perf_counter()
            )

            for group in groups:
                for matchday in range(
                    1,
                    matchday_count + 1,
                ):
                    rebuild_matchday_scores(
                        group_id=group.id,
                        matchday=matchday,
                    )

                rebuild_group_timeline(
                    group_id=group.id,
                )

                rebuild_group_bonus_points(
                    group_id=group.id,
                )

            full_rebuild_seconds = (
                perf_counter()
                - full_rebuild_started
            )

            actual_matchday_scores = (
                MatchdayScore.objects
                .filter(
                    group__tournament=(
                        tournament
                    ),
                )
                .count()
            )

            actual_standings = (
                GroupStanding.objects
                .filter(
                    group__tournament=(
                        tournament
                    ),
                )
                .count()
            )

            if (
                actual_matchday_scores
                != expected_matchday_scores
            ):
                raise CommandError(
                    "Unerwartete Zahl an "
                    "MatchdayScore-Zeilen: "
                    f"{actual_matchday_scores} "
                    f"statt "
                    f"{expected_matchday_scores}."
                )

            if (
                actual_standings
                != expected_standings
            ):
                raise CommandError(
                    "Unerwartete Zahl an "
                    "GroupStanding-Zeilen: "
                    f"{actual_standings} statt "
                    f"{expected_standings}."
                )

            # --------------------------------------------------
            # Normale Ergebnisänderung messen
            # --------------------------------------------------

            changed_match = matches[-1]

            Match.objects.filter(
                pk=changed_match.pk,
            ).update(
                home_score=1,
                away_score=1,
            )

            incremental_started = (
                perf_counter()
            )

            processed_groups = (
                process_match_change(
                    match_id=changed_match.id,
                    previous_matchday=(
                        changed_match.matchday
                    ),
                    rebuild_bonus=False,
                )
            )

            incremental_seconds = (
                perf_counter()
                - incremental_started
            )

            changed_predictions = (
                Prediction.objects
                .filter(
                    match=changed_match,
                    points=0,
                )
                .count()
            )

            expected_changed_predictions = (
                user_count
                * group_count
            )

            if (
                changed_predictions
                != expected_changed_predictions
            ):
                raise CommandError(
                    "Die Punkte der geänderten "
                    "Tipps wurden nicht vollständig "
                    "aktualisiert."
                )

            # --------------------------------------------------
            # Ergebnisse
            # --------------------------------------------------

            self.stdout.write(
                self.style.SUCCESS(
                    "Testdaten erfolgreich erzeugt."
                )
            )

            self.stdout.write(
                (
                    "Erzeugung der Testdaten: "
                    f"{seed_seconds:.3f} Sekunden"
                )
            )

            self.stdout.write(
                (
                    "Vollständiger Rebuild: "
                    f"{full_rebuild_seconds:.3f} "
                    "Sekunden"
                )
            )

            self.stdout.write(
                (
                    "Inkrementelle "
                    "Ergebnisänderung: "
                    f"{incremental_seconds:.3f} "
                    "Sekunden"
                )
            )

            self.stdout.write(
                (
                    "Bearbeitete Gruppen bei "
                    "Ergebnisänderung: "
                    f"{processed_groups}"
                )
            )

            self.stdout.write("")
            self.stdout.write(
                (
                    "Prediction-Zeilen: "
                    f"{actual_predictions:,}"
                )
            )

            self.stdout.write(
                (
                    "MatchdayScore-Zeilen: "
                    f"{actual_matchday_scores:,}"
                )
            )

            self.stdout.write(
                (
                    "GroupStanding-Zeilen: "
                    f"{actual_standings:,}"
                )
            )

            self.stdout.write("")

            # Sämtliche Benchmark-Daten werden
            # beim Verlassen des atomic-Blocks
            # zurückgerollt.
            transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                "Benchmark abgeschlossen. "
                "Alle Testdaten wurden zurückgerollt."
            )
        )
