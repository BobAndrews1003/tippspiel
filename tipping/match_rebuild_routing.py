from .models import Match
from .result_processing import (
    process_match_change,
    process_match_delete,
)
from .standing_jobs import (
    enqueue_standing_rebuild,
)


ROUTE_IGNORED = "ignored"
ROUTE_PROCESSED = "processed"
ROUTE_QUEUED = "queued"


def _has_later_result_matchday(
    *,
    tournament_id: int,
    start_matchday: int,
) -> bool:
    """
    Prüft, ob nach dem frühesten betroffenen Spieltag
    bereits ein weiterer vollständig ausgewerteter
    Spieltag existiert.

    In diesem Fall müssen historische kumulierte Ränge
    neu aufgebaut werden. Diese Arbeit wird in die
    dauerhafte Warteschlange verschoben.
    """

    return Match.objects.filter(
        tournament_id=tournament_id,
        matchday__gt=start_matchday,
        home_score__isnull=False,
        away_score__isnull=False,
    ).exists()


def route_match_change(
    *,
    match_id: int,
    previous_matchday: int | None = None,
) -> str:
    """
    Leitet eine Ergebnis- oder Spieltagsänderung weiter.

    - Änderung am neuesten ausgewerteten Spieltag:
      sofortige synchrone Verarbeitung.
    - Historische Änderung mit späteren Ergebnissen:
      dauerhafter Background-Job.
    """

    match = (
        Match.objects
        .filter(
            pk=match_id,
        )
        .only(
            "id",
            "tournament_id",
            "matchday",
        )
        .first()
    )

    if match is None:
        return ROUTE_IGNORED

    affected_matchdays = {
        matchday
        for matchday in (
            previous_matchday,
            match.matchday,
        )
        if matchday is not None
    }

    # Auch ein Spiel ohne Spieltag kann Prediction.points
    # beeinflussen. Deshalb wird der normale Prozessor
    # weiterhin ausgeführt.
    if not affected_matchdays:
        process_match_change(
            match_id=match_id,
            previous_matchday=previous_matchday,
            rebuild_bonus=False,
        )

        return ROUTE_PROCESSED

    start_matchday = min(
        affected_matchdays
    )

    if _has_later_result_matchday(
        tournament_id=match.tournament_id,
        start_matchday=start_matchday,
    ):
        enqueue_standing_rebuild(
            tournament_id=match.tournament_id,
            affected_matchdays=(
                affected_matchdays
            ),
            match_ids=[
                match_id,
            ],
            rebuild_bonus=False,
        )

        return ROUTE_QUEUED

    process_match_change(
        match_id=match_id,
        previous_matchday=previous_matchday,
        rebuild_bonus=False,
    )

    return ROUTE_PROCESSED


def route_match_delete(
    *,
    tournament_id: int,
    matchday: int | None,
    had_result: bool,
) -> str:
    """
    Leitet das Löschen eines ausgewerteten Spiels weiter.

    Historische Löschungen werden in die Queue gestellt.
    Das Löschen eines Spiels am letzten ausgewerteten
    Spieltag wird sofort verarbeitet.
    """

    if (
        matchday is None
        or not had_result
    ):
        return ROUTE_IGNORED

    if _has_later_result_matchday(
        tournament_id=tournament_id,
        start_matchday=matchday,
    ):
        enqueue_standing_rebuild(
            tournament_id=tournament_id,
            affected_matchdays=[
                matchday,
            ],
            match_ids=[],
            rebuild_bonus=False,
        )

        return ROUTE_QUEUED

    process_match_delete(
        tournament_id=tournament_id,
        matchday=matchday,
        had_result=had_result,
    )

    return ROUTE_PROCESSED
