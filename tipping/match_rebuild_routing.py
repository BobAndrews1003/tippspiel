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
    return Match.objects.filter(
        tournament_id=tournament_id,
        matchday__gt=start_matchday,
        home_score__isnull=False,
        away_score__isnull=False,
    ).exists()


def _combine_routes(
    *routes: str,
) -> str:
    if ROUTE_QUEUED in routes:
        return ROUTE_QUEUED

    if ROUTE_PROCESSED in routes:
        return ROUTE_PROCESSED

    return ROUTE_IGNORED


def _route_current_match_change(
    *,
    match: Match,
    previous_matchday: int | None,
) -> str:
    affected_matchdays = {
        matchday
        for matchday in (
            previous_matchday,
            match.matchday,
        )
        if matchday is not None
    }

    if not affected_matchdays:
        process_match_change(
            match_id=match.id,
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
                match.id,
            ],
            group_ids=[],
            rebuild_bonus=False,
        )

        return ROUTE_QUEUED

    process_match_change(
        match_id=match.id,
        previous_matchday=previous_matchday,
        rebuild_bonus=False,
    )

    return ROUTE_PROCESSED


def route_match_change(
    *,
    match_id: int,
    previous_matchday: int | None = None,
    previous_tournament_id: int | None = None,
    previous_had_result: bool = False,
) -> str:
    """
    Verarbeitet eine Match-Änderung im bisherigen und
    aktuellen Turnier.

    Ein Turnierwechsel ohne vorhandene Tipps wird wie das
    Entfernen aus dem alten und das Hinzufügen zum neuen
    Turnier behandelt.
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
            "home_score",
            "away_score",
        )
        .first()
    )

    if match is None:
        return ROUTE_IGNORED

    tournament_changed = (
        previous_tournament_id is not None
        and previous_tournament_id
        != match.tournament_id
    )

    if not tournament_changed:
        return _route_current_match_change(
            match=match,
            previous_matchday=previous_matchday,
        )

    routes = []

    # Im bisherigen Turnier wirkt der Wechsel wie
    # das Entfernen des früheren Spiels.
    if previous_had_result:
        routes.append(
            route_match_delete(
                tournament_id=(
                    previous_tournament_id
                ),
                matchday=previous_matchday,
                had_result=True,
            )
        )

    current_has_result = (
        match.home_score is not None
        and match.away_score is not None
    )

    # Im neuen Turnier wirkt der Wechsel wie ein
    # neu hinzugefügtes ausgewertetes Spiel.
    if current_has_result:
        routes.append(
            _route_current_match_change(
                match=match,
                previous_matchday=None,
            )
        )

    return _combine_routes(
        *routes
    )


def route_match_delete(
    *,
    tournament_id: int,
    matchday: int | None,
    had_result: bool,
) -> str:
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
            group_ids=[],
            rebuild_bonus=False,
        )

        return ROUTE_QUEUED

    process_match_delete(
        tournament_id=tournament_id,
        matchday=matchday,
        had_result=had_result,
    )

    return ROUTE_PROCESSED
