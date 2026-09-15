import csv
import re
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tipping.models import (
    Match,
    Tournament,
    TournamentStage,
)
from tipping.tournament_stages import ensure_default_stages


def _pick(row: dict, candidates: list[str]) -> str | None:
    """Return first non-empty value found for any candidate key."""
    for key in candidates:
        if key in row and row[key] is not None:
            val = str(row[key]).strip()
            if val != "" and val.lower() != "none":
                return val
    return None


def _parse_datetime(date_str: str | None, time_str: str | None):
    """
    Your CSV provides dateEvent (YYYY-MM-DD) but usually no time.
    We set a default kickoff time (12:00) so the DateTimeField is valid.
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Format: YYYY-MM-DD
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    # If no time present → default to 12:00
    return datetime.combine(d, datetime.strptime("23:59", "%H:%M").time())


def _to_int(val: str | None):
    if val is None:
        return None

    s = str(val).strip()
    if s == "":
        return None

    # Extract first number from strings like "Fecha 1", "Jornada 12", "Round 3"
    m = re.search(r"\d+", s)
    if m:
        return int(m.group())

    return None


STAGE_ALIASES = {
    "regular": TournamentStage.Code.REGULAR,
    "fase_regular": TournamentStage.Code.REGULAR,
    "hexagonal_final": TournamentStage.Code.HEXAGONAL_FINAL,
    "cuadrangular": TournamentStage.Code.CUADRANGULAR,
    "hexagonal_de_descenso": (
        TournamentStage.Code.HEXAGONAL_DESCENT
    ),
    "hexagonal_descenso": (
        TournamentStage.Code.HEXAGONAL_DESCENT
    ),
}


def _stage_code(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = re.sub(
        r"[^a-z0-9]+",
        "_",
        value.strip().lower(),
    ).strip("_")

    return STAGE_ALIASES.get(normalized)



class Command(BaseCommand):
    help = "Import matches from a CSV (e.g., TheSportsDB export) into the DB."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to CSV file, e.g. ligapro.csv")
        parser.add_argument(
            "--tournament",
            type=str,
            default="LigaPro Ecuador",
            help='Tournament name to import into (default: "LigaPro Ecuador")',
        )
        parser.add_argument(
            "--update-results",
            action="store_true",
            help="If set, also update home_score/away_score when present in CSV.",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"])
        tournament_name = options["tournament"]
        update_results = options["update_results"]

        if not csv_path.exists():
            raise CommandError(f"CSV file not found: {csv_path}")

        tournament, _ = Tournament.objects.get_or_create(name=tournament_name)
        ensure_default_stages(tournament)
        stages_by_code = {
            stage.code: stage
            for stage in tournament.stages.all()
        }

        created = 0
        updated = 0
        skipped = 0

        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row / field names.")

            for row in reader:
                home = _pick(row, ["Equipo local", "strHomeTeam", "HomeTeam", "home_team", "Home", "Team1"])
                away = _pick(row, ["Equipo visitante", "strAwayTeam", "AwayTeam", "away_team", "Away", "Team2"])

                # Date / time
                timestamp = _pick(row, ["strTimestamp", "timestamp", "dateTime", "datetime"])
                date_event = _pick(row, ["dateEvent", "Date", "date", "event_date"])
                time_event = _pick(row, ["strTime", "Time", "time", "event_time"])

                # Matchday (Fecha = Spieltag/Runde)
                matchday_raw = _pick(row, ["Fecha", "fecha", "matchday", "round"])
                stage_raw = _pick(
                    row,
                    ["Fase", "fase", "stage", "phase"],
                )
                stage_round_raw = _pick(
                    row,
                    [
                        "Fecha de fase",
                        "fecha_fase",
                        "stage_round",
                        "phase_round",
                    ],
                )

                kickoff_dt = _parse_datetime(timestamp or date_event, time_event)

                if not home or not away or kickoff_dt is None:
                    skipped += 1
                    continue

                kickoff = timezone.make_aware(kickoff_dt, timezone.get_current_timezone())

                # Convert matchday to int (or None)
                md = _to_int(matchday_raw)
                stage_code = _stage_code(stage_raw)

                if stage_raw and stage_code is None:
                    skipped += 1
                    continue

                stage = (
                    stages_by_code.get(stage_code)
                    if stage_code
                    else (
                        stages_by_code.get(
                            TournamentStage.Code.REGULAR
                        )
                        if md is not None
                        else None
                    )
                )
                stage_round = _to_int(stage_round_raw)

                if (
                    stage is not None
                    and stage_round is None
                ):
                    if stage.code == TournamentStage.Code.REGULAR:
                        stage_round = md
                    elif md is not None and md >= 31:
                        stage_round = md - 30

                if (
                    stage is not None
                    and (
                        stage_round is None
                        or stage_round > stage.round_count
                    )
                ):
                    skipped += 1
                    continue

                # Optional scores
                hs = _pick(row, ["Home Score", "intHomeScore", "HomeScore", "home_score", "score_home"])
                aws = _pick(row, ["Away Score", "intAwayScore", "AwayScore", "away_score", "score_away"])
                hs_i = _to_int(hs)
                aws_i = _to_int(aws)

                # Uniqueness strategy: tournament + home + away + kickoff
                obj = Match.objects.filter(
                    tournament=tournament,
                    home_team=home,
                    away_team=away,
                    kickoff=kickoff,
                ).first()

                if obj is None:
                    obj = Match(
                        tournament=tournament,
                        home_team=home,
                        away_team=away,
                        kickoff=kickoff,
                        matchday=md,
                        stage=stage,
                        stage_round=stage_round,
                    )

                    if update_results and hs_i is not None and aws_i is not None:
                        obj.home_score = hs_i
                        obj.away_score = aws_i

                    obj.save()
                    created += 1

                else:
                    changed = False

                    # Always update matchday if missing/different
                    if obj.matchday != md:
                        obj.matchday = md
                        changed = True

                    if obj.stage_id != getattr(stage, "id", None):
                        obj.stage = stage
                        changed = True

                    if obj.stage_round != stage_round:
                        obj.stage_round = stage_round
                        changed = True

                    # Update results only if flag is set and values exist
                    if update_results and hs_i is not None and aws_i is not None:
                        if obj.home_score != hs_i or obj.away_score != aws_i:
                            obj.home_score = hs_i
                            obj.away_score = aws_i
                            changed = True

                    if changed:
                        obj.save()
                        updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Import done. Created: {created}, Updated: {updated}, Skipped: {skipped}"
        ))
