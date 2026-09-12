from collections import defaultdict

from django.db import transaction

from .models import (
    Group,
    Match,
    MatchdayScore,
    Prediction,
)
from .scoring import points_for_prediction
from .standing_refresh import (
    rebuild_group_standing_with_bonus_fallback,
)
from .standing_jobs import enqueue_standing_rebuild
from .standings import (
    rebuild_group_timeline,
    rebuild_matchday_scores,
)


def _match_has_result(match: Match) -> bool:
    return (
        match.home_score is not None
        and match.away_score is not None
    )


def _add_affected_group_matchday(
    affected_by_group: dict[int, set[int]],
    *,
    group_id: int | None,
    match: Match | None,
) -> None:
    """
    Registriert eine Gruppe und einen Spieltag nur,
    wenn das Spiel vollständig ausgewertet ist.
    """

    if (
        group_id is None
        or match is None
        or match.matchday is None
        or not _match_has_result(match)
    ):
        return

    affected_by_group[
        group_id
    ].add(
        match.matchday
    )


def _rebuild_affected_groups(
    affected_by_group: dict[int, set[int]],
) -> int:
    """
    Aktualisiert betroffene Gruppen sofort oder legt bei
    historischen Änderungen einen gruppenspezifischen Job an.
    """

    processed_groups = 0

    for group_id in sorted(
        affected_by_group
    ):
        matchdays = affected_by_group[
            group_id
        ]

        if not matchdays:
            continue

        group = (
            Group.objects
            .filter(
                pk=group_id,
                memberships__isnull=False,
                memberships__is_active=True,
            )
            .only(
                "id",
                "tournament_id",
            )
            .distinct()
            .first()
        )

        if group is None:
            MatchdayScore.objects.filter(
                group_id=group_id,
            ).delete()

            continue

        start_matchday = min(matchdays)

        has_later_results = (
            Match.objects.filter(
                tournament_id=(
                    group.tournament_id
                ),
                matchday__gt=start_matchday,
                home_score__isnull=False,
                away_score__isnull=False,
            ).exists()
        )

        if has_later_results:
            enqueue_standing_rebuild(
                tournament_id=(
                    group.tournament_id
                ),
                affected_matchdays=matchdays,
                match_ids=[],
                group_ids=[
                    group_id,
                ],
                rebuild_bonus=False,
            )

            processed_groups += 1
            continue

        for matchday in sorted(matchdays):
            rebuild_matchday_scores(
                group_id=group_id,
                matchday=matchday,
            )

        rebuild_group_timeline(
            group_id=group_id,
            start_matchday=start_matchday,
        )

        rebuild_group_standing_with_bonus_fallback(
            group_id=group_id,
        )

        processed_groups += 1

    return processed_groups


@transaction.atomic
def process_prediction_change(
    *,
    prediction_id: int,
    previous_group_id: int | None = None,
    previous_match_id: int | None = None,
) -> int:
    """
    Verarbeitet das Erstellen oder Ändern eines Tipps.

    Bei bereits ausgewerteten Spielen werden:

    1. Prediction.points neu berechnet,
    2. MatchdayScore aktualisiert,
    3. historische Ränge neu berechnet,
    4. GroupStanding aktualisiert.

    Bei noch nicht ausgewerteten Spielen ist kein
    Ranglisten-Rebuild erforderlich.
    """

    prediction = (
        Prediction.objects
        .select_for_update()
        .select_related("match")
        .filter(
            pk=prediction_id,
        )
        .first()
    )

    if prediction is None:
        return 0

    current_match = prediction.match

    calculated_points = points_for_prediction(
        current_match,
        prediction,
    )

    if prediction.points != calculated_points:
        # QuerySet.update() wird absichtlich verwendet,
        # damit kein weiteres Prediction-Signal ausgelöst wird.
        Prediction.objects.filter(
            pk=prediction.id,
        ).update(
            points=calculated_points,
        )

        prediction.points = calculated_points

    affected_by_group: dict[
        int,
        set[int],
    ] = defaultdict(set)

    _add_affected_group_matchday(
        affected_by_group,
        group_id=prediction.group_id,
        match=current_match,
    )

    previous_location_changed = (
        previous_group_id is not None
        and previous_match_id is not None
        and (
            previous_group_id
            != prediction.group_id
            or previous_match_id
            != prediction.match_id
        )
    )

    if previous_location_changed:
        previous_match = (
            Match.objects
            .filter(
                pk=previous_match_id,
            )
            .first()
        )

        _add_affected_group_matchday(
            affected_by_group,
            group_id=previous_group_id,
            match=previous_match,
        )

    return _rebuild_affected_groups(
        affected_by_group
    )


@transaction.atomic
def process_prediction_delete(
    *,
    group_id: int,
    match_id: int,
) -> int:
    """
    Aktualisiert das Read Model nach dem direkten
    Löschen eines Tipps.

    Kaskaden beim Löschen eines Spiels, einer Gruppe
    oder eines Nutzers werden bereits von den jeweiligen
    Verarbeitungspfaden behandelt.
    """

    match = (
        Match.objects
        .filter(
            pk=match_id,
        )
        .first()
    )

    if match is None:
        return 0

    affected_by_group: dict[
        int,
        set[int],
    ] = defaultdict(set)

    _add_affected_group_matchday(
        affected_by_group,
        group_id=group_id,
        match=match,
    )

    return _rebuild_affected_groups(
        affected_by_group
    )
