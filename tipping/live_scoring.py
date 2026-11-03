from __future__ import annotations

from dataclasses import dataclass

from .group_scoring import scoring_values_for_group
from .models import Group, Match, Prediction
from .scoring import score_prediction_for_result


@dataclass(frozen=True)
class LiveMatchdaySnapshot:
    totals_by_user: dict[int, int]
    ranks_by_user: dict[int, int]
    cell_points: dict[tuple[int, int], int | None]


def build_live_matchday_snapshot(
    *,
    group: Group,
    matches: list[Match],
    user_ids: list[int],
) -> LiveMatchdaySnapshot:
    """Berechnet eine flüchtige Live-Tabelle ohne Endwerte zu speichern."""

    totals_by_user = {
        user_id: 0
        for user_id in user_ids
    }
    cell_points = {}

    if not matches or not user_ids:
        return LiveMatchdaySnapshot(
            totals_by_user=totals_by_user,
            ranks_by_user={
                user_id: 1
                for user_id in user_ids
            },
            cell_points=cell_points,
        )

    matches_by_id = {
        match.id: match
        for match in matches
    }
    scoring_values = scoring_values_for_group(
        group
    )
    predictions = (
        Prediction.objects
        .filter(
            group=group,
            user_id__in=user_ids,
            match_id__in=matches_by_id,
        )
        .select_related("group__scoring_settings")
    )

    for prediction in predictions:
        match = matches_by_id[
            prediction.match_id
        ]
        points = None

        if match.has_result:
            if prediction.points is not None:
                points = prediction.points

            else:
                points = score_prediction_for_result(
                    prediction,
                    home_score=match.home_score,
                    away_score=match.away_score,
                    scoring_values=scoring_values,
                ).points

        elif match.is_live:
            points = score_prediction_for_result(
                prediction,
                home_score=match.live_home_score,
                away_score=match.live_away_score,
                scoring_values=scoring_values,
            ).points

        cell_points[
            (
                prediction.user_id,
                prediction.match_id,
            )
        ] = points

        if points is not None:
            totals_by_user[
                prediction.user_id
            ] += points

    ranks_by_user = {}
    previous_points = None
    previous_rank = 0

    for index, (user_id, points) in enumerate(
        sorted(
            totals_by_user.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        ),
        start=1,
    ):
        if points != previous_points:
            previous_rank = index
            previous_points = points

        ranks_by_user[user_id] = previous_rank

    return LiveMatchdaySnapshot(
        totals_by_user=totals_by_user,
        ranks_by_user=ranks_by_user,
        cell_points=cell_points,
    )
