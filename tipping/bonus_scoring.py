from collections.abc import Iterable
from datetime import datetime

from django.utils import timezone

from .models import (
    BonusPrediction,
    Match,
    Tournament,
)


def normalize_bonus_value(value: str) -> str:
    """
    Vereinheitlicht Bonuswerte für den Vergleich.
    """

    return (value or "").strip().lower()


def get_bonus_lock_time(
    tournament: Tournament,
) -> datetime | None:
    """
    Bonustipps werden mit dem ersten Saisonspiel gesperrt.

    Falls noch keine Spiele existieren, wird season_start
    als Ersatz verwendet.
    """

    first_kickoff = (
        Match.objects
        .filter(
            tournament=tournament,
        )
        .order_by("kickoff")
        .values_list(
            "kickoff",
            flat=True,
        )
        .first()
    )

    return (
        first_kickoff
        or tournament.season_start
    )


def bonus_is_revealed(
    tournament: Tournament,
    *,
    at: datetime | None = None,
) -> bool:
    """
    Prüft, ob Bonustipps sichtbar und wertbar sind.
    """

    current_time = at or timezone.now()

    lock_time = get_bonus_lock_time(
        tournament
    )

    return bool(
        lock_time
        and current_time >= lock_time
    )


def bonus_points_for_user(
    tournament: Tournament,
    predictions: Iterable[BonusPrediction],
) -> int:
    """
    Vergibt fünf Punkte pro richtigem Bonustipp.

    Doppelte Nennung desselben Absteigers wird nicht
    zweimal gewertet.
    """

    real_autumn_champion = normalize_bonus_value(
        tournament.autumn_champion
    )

    real_champion = normalize_bonus_value(
        tournament.champion
    )

    real_first_coach_sacked = (
        normalize_bonus_value(
            tournament.first_coach_sacked
        )
    )

    real_top_scorer = normalize_bonus_value(
        tournament.top_scorer
    )

    relegated_teams = {
        normalize_bonus_value(team)
        for team in (
            tournament.relegated_teams
            or ""
        ).split(",")
        if normalize_bonus_value(team)
    }

    points = 0
    counted_relegations: set[str] = set()

    for prediction in predictions:
        bonus_type = prediction.bonus_type

        value = normalize_bonus_value(
            prediction.value
        )

        if not value:
            continue

        if (
            bonus_type == "herbstmeister"
            and real_autumn_champion
            and value == real_autumn_champion
        ):
            points += 5

        elif (
            bonus_type == "meister"
            and real_champion
            and value == real_champion
        ):
            points += 5

        elif (
            bonus_type == "trainer_first"
            and real_first_coach_sacked
            and value
            == real_first_coach_sacked
        ):
            points += 5

        elif (
            bonus_type == "topscorer"
            and real_top_scorer
            and value == real_top_scorer
        ):
            points += 5

        elif (
            bonus_type
            in {
                "relegation1",
                "relegation2",
            }
            and value in relegated_teams
            and value
            not in counted_relegations
        ):
            points += 5

            counted_relegations.add(
                value
            )

    return points
