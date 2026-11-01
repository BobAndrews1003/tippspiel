from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from .group_scoring import scoring_values_for_group
from .models import Match, Prediction
from .scoring_config import ScoringValues


@dataclass(frozen=True)
class PredictionScore:
    category: str | None
    points: int | None


def prediction_score_category(
    match: Match,
    prediction: Prediction | None,
) -> str | None:
    """Bestimmt die Trefferkategorie unabhängig von der Punktzahl."""

    if prediction is None:
        return None

    if (
        match.home_score is None
        or match.away_score is None
        or prediction.pred_home is None
        or prediction.pred_away is None
    ):
        return None

    actual_home = match.home_score
    actual_away = match.away_score
    predicted_home = prediction.pred_home
    predicted_away = prediction.pred_away

    if (
        predicted_home == actual_home
        and predicted_away == actual_away
    ):
        return Prediction.ScoreCategory.EXACT

    actual_difference = actual_home - actual_away
    predicted_difference = predicted_home - predicted_away

    if predicted_difference == actual_difference:
        return Prediction.ScoreCategory.GOAL_DIFFERENCE

    def tendency(
        home_score: int,
        away_score: int,
    ) -> int:
        if home_score > away_score:
            return 1

        if home_score < away_score:
            return -1

        return 0

    if tendency(
        predicted_home,
        predicted_away,
    ) == tendency(
        actual_home,
        actual_away,
    ):
        return Prediction.ScoreCategory.TENDENCY

    return Prediction.ScoreCategory.INCORRECT


def score_prediction(
    match: Match,
    prediction: Prediction | None,
    *,
    scoring_values: ScoringValues | None = None,
) -> PredictionScore:
    category = prediction_score_category(
        match,
        prediction,
    )

    if category is None:
        return PredictionScore(
            category=None,
            points=None,
        )

    if scoring_values is None:
        group = None

        if (
            prediction is not None
            and prediction.group_id is not None
        ):
            group = prediction.group

        scoring_values = scoring_values_for_group(group)

    points_by_category = {
        Prediction.ScoreCategory.EXACT: (
            scoring_values.exact_points
        ),
        Prediction.ScoreCategory.GOAL_DIFFERENCE: (
            scoring_values.goal_difference_points
        ),
        Prediction.ScoreCategory.TENDENCY: (
            scoring_values.tendency_points
        ),
        Prediction.ScoreCategory.INCORRECT: (
            scoring_values.incorrect_points
        ),
    }

    return PredictionScore(
        category=category,
        points=points_by_category[category],
    )


def points_for_prediction(
    match: Match,
    prediction: Prediction | None,
    *,
    scoring_values: ScoringValues | None = None,
) -> int | None:
    """
    Berechnet die Punkte eines Tipps.

    Die Trefferkategorie ist fest definiert. Die dafür vergebenen
    Punkte stammen aus dem System der jeweiligen Gruppe. Für Tipps
    ohne Gruppe gilt das Puntero-Standardmodell 4/3/2/0.

    None wird zurückgegeben, wenn das Spiel noch kein
    vollständiges Ergebnis hat oder der Tipp unvollständig ist.
    """

    return score_prediction(
        match,
        prediction,
        scoring_values=scoring_values,
    ).points


@transaction.atomic
def recalculate_points_for_match(
    match: Match,
) -> int:
    """
    Berechnet die Punkte aller Tipps eines Spiels neu.

    Gibt die Anzahl der aktualisierten Tipps zurück.
    """

    predictions = list(
        Prediction.objects
        .select_for_update()
        .select_related(
            "group__scoring_settings",
        )
        .filter(
            match=match,
        )
        .only(
            "id",
            "match_id",
            "pred_home",
            "pred_away",
            "points",
            "score_category",
            "group__id",
            "group__scoring_settings__exact_points",
            (
                "group__scoring_settings__"
                "goal_difference_points"
            ),
            "group__scoring_settings__tendency_points",
            "group__scoring_settings__incorrect_points",
        )
    )

    if not predictions:
        return 0

    # Wenn das Ergebnis entfernt oder unvollständig ist,
    # werden vorhandene Punkte wieder gelöscht.
    if (
        match.home_score is None
        or match.away_score is None
    ):
        Prediction.objects.filter(
            id__in=[
                prediction.id
                for prediction in predictions
            ]
        ).update(
            points=None,
            score_category=None,
        )

        return len(predictions)

    for prediction in predictions:
        result = score_prediction(
            match,
            prediction,
        )
        prediction.points = result.points
        prediction.score_category = result.category

    Prediction.objects.bulk_update(
        predictions,
        [
            "points",
            "score_category",
        ],
        batch_size=1000,
    )

    return len(predictions)


def recalculate_points_for_match_id(
    match_id: int,
) -> int:
    """
    Variante für Signale und Hintergrundprozesse.
    """

    match = Match.objects.filter(
        pk=match_id,
    ).first()

    if match is None:
        return 0

    return recalculate_points_for_match(
        match
    )
