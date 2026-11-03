from collections import Counter
import csv
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.db import transaction
from django.db.models import Count

from tipping.models import (
    Match,
    Tournament,
    TournamentStage,
)
from tipping.management.commands.import_matches import (
    _pick,
    _stage_code,
    _to_int,
)


EXPECTED_STAGE_COUNTS = {
    TournamentStage.Code.REGULAR: 240,
    TournamentStage.Code.HEXAGONAL_FINAL: 30,
    TournamentStage.Code.CUADRANGULAR: 12,
    TournamentStage.Code.HEXAGONAL_DESCENT: 30,
}
EXPECTED_MATCH_COUNT = sum(
    EXPECTED_STAGE_COUNTS.values()
)
EXPECTED_MATCHDAYS = set(range(1, 41))


def load_expected_schedule(
    csv_paths: list[Path],
) -> set[tuple[str, str, int, str, int]]:
    expected = set()
    row_count = 0

    for csv_path in csv_paths:
        with csv_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            reader = csv.DictReader(csv_file)

            if not reader.fieldnames:
                raise CommandError(
                    f"Spielplan-Datei ohne Kopfzeile: {csv_path}"
                )

            for row in reader:
                row_count += 1
                home_team = _pick(
                    row,
                    ["Equipo local", "home_team"],
                )
                away_team = _pick(
                    row,
                    ["Equipo visitante", "away_team"],
                )
                matchday = _to_int(
                    _pick(
                        row,
                        ["Fecha", "matchday"],
                    )
                )
                raw_stage = _pick(
                    row,
                    ["Fase", "stage"],
                )
                stage_code = (
                    _stage_code(raw_stage)
                    if raw_stage
                    else TournamentStage.Code.REGULAR
                )
                stage_round = _to_int(
                    _pick(
                        row,
                        ["Fecha de fase", "stage_round"],
                    )
                )

                if stage_round is None and matchday is not None:
                    if stage_code == TournamentStage.Code.REGULAR:
                        stage_round = matchday
                    elif matchday >= 31:
                        stage_round = matchday - 30

                if (
                    not home_team
                    or not away_team
                    or matchday is None
                    or stage_code is None
                    or stage_round is None
                ):
                    raise CommandError(
                        "Ungültige Spielplan-Zeile in "
                        f"{csv_path}."
                    )

                expected.add(
                    (
                        home_team,
                        away_team,
                        matchday,
                        str(stage_code),
                        stage_round,
                    )
                )

    if (
        row_count != EXPECTED_MATCH_COUNT
        or len(expected) != EXPECTED_MATCH_COUNT
    ):
        raise CommandError(
            "Die versionierten LigaPro-Dateien enthalten nicht "
            f"exakt {EXPECTED_MATCH_COUNT} eindeutige Spiele."
        )

    return expected


def validate_ligapro_schedule(
    tournament: Tournament,
    *,
    expected_schedule: set[
        tuple[str, str, int, str, int]
    ],
) -> None:
    matches = tournament.matches.all()
    match_count = matches.count()

    if match_count != EXPECTED_MATCH_COUNT:
        raise CommandError(
            "Der LigaPro-Spielplan ist unvollständig: "
            f"{match_count} statt {EXPECTED_MATCH_COUNT} Spiele. "
            "Der Bestand wird aus Sicherheitsgründen nicht ergänzt."
        )

    stage_counts = Counter(
        matches.values_list(
            "stage__code",
            flat=True,
        )
    )

    if stage_counts != Counter(EXPECTED_STAGE_COUNTS):
        readable_counts = ", ".join(
            f"{stage or 'ohne Phase'}={count}"
            for stage, count in sorted(
                stage_counts.items(),
                key=lambda item: str(item[0]),
            )
        )
        raise CommandError(
            "Die LigaPro-Phasen entsprechen nicht dem erwarteten "
            f"Spielplan ({readable_counts})."
        )

    matchdays = set(
        matches.values_list(
            "matchday",
            flat=True,
        )
    )

    if matchdays != EXPECTED_MATCHDAYS:
        raise CommandError(
            "Der LigaPro-Spielplan enthält nicht exakt die "
            "globalen Spieltage 1 bis 40."
        )

    if matches.filter(stage_round__isnull=True).exists():
        raise CommandError(
            "Mindestens ein LigaPro-Spiel hat keine Phasenrunde."
        )

    duplicate_count = (
        matches
        .values(
            "home_team",
            "away_team",
            "matchday",
        )
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .count()
    )

    if duplicate_count:
        raise CommandError(
            "Der LigaPro-Spielplan enthält doppelte Partien."
        )

    actual_schedule = set(
        matches.values_list(
            "home_team",
            "away_team",
            "matchday",
            "stage__code",
            "stage_round",
        )
    )

    if actual_schedule != expected_schedule:
        missing_count = len(
            expected_schedule - actual_schedule
        )
        unexpected_count = len(
            actual_schedule - expected_schedule
        )
        raise CommandError(
            "Der LigaPro-Spielplan weicht von den versionierten "
            "CSV-Dateien ab: "
            f"{missing_count} fehlend, "
            f"{unexpected_count} unerwartet."
        )


class Command(BaseCommand):
    help = (
        "Importiert den LigaPro-Spielplan für eine leere Datenbank "
        "und validiert bestehende Installationen idempotent."
    )

    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--regular-csv",
            default=str(
                Path(settings.BASE_DIR) / "ligapro.csv"
            ),
            help="CSV der regulären LigaPro-Saison.",
        )
        parser.add_argument(
            "--final-rounds-csv",
            default=str(
                Path(settings.BASE_DIR)
                / "ligapro_final_rounds.csv"
            ),
            help="CSV der drei LigaPro-Finalphasen.",
        )
        parser.add_argument(
            "--tournament",
            default=settings.LIGAPRO_SYNC_TOURNAMENT,
            help="Lokaler Turniername.",
        )

    def handle(self, *args, **options):
        tournament_name = options["tournament"].strip()
        csv_paths = [
            Path(options["regular_csv"]),
            Path(options["final_rounds_csv"]),
        ]

        if not tournament_name:
            raise CommandError(
                "Der Turniername darf nicht leer sein."
            )

        for csv_path in csv_paths:
            if not csv_path.is_file():
                raise CommandError(
                    f"Spielplan-Datei nicht gefunden: {csv_path}"
                )

        expected_schedule = load_expected_schedule(
            csv_paths
        )

        tournament = Tournament.objects.filter(
            name=tournament_name,
        ).first()

        if (
            tournament is not None
            and tournament.matches.exists()
        ):
            validate_ligapro_schedule(
                tournament,
                expected_schedule=expected_schedule,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    "LigaPro-Spielplan bereits vollständig: "
                    f"{EXPECTED_MATCH_COUNT} Spiele."
                )
            )
            return

        with transaction.atomic():
            for csv_path in csv_paths:
                call_command(
                    "import_matches",
                    str(csv_path),
                    tournament=tournament_name,
                    stdout=self.stdout,
                    stderr=self.stderr,
                )

            tournament = Tournament.objects.get(
                name=tournament_name,
            )
            validate_ligapro_schedule(
                tournament,
                expected_schedule=expected_schedule,
            )

        self.stdout.write(
            self.style.SUCCESS(
                "LigaPro-Erstimport erfolgreich: "
                f"{EXPECTED_MATCH_COUNT} Spiele in 40 Spieltagen."
            )
        )
