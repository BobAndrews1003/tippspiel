from __future__ import annotations

from django.db import transaction

from .models import Match, Prediction


def points_for_prediction(
    match: Match,
    prediction: Prediction | None,
) -> int | None:
    """
    Berechnet die Punkte eines Tipps.

    Regeln:
    - 4 Punkte: exaktes Ergebnis
    - 3 Punkte: richtige Tordifferenz
    - 2 Punkte: richtige Tendenz
    - 0 Punkte: falscher Tipp

    None wird zurückgegeben, wenn das Spiel noch kein
    vollständiges Ergebnis hat oder der Tipp unvollständig ist.
    """

    if prediction is None:
        return None

    if (
        match.home_score is None
        or match.away_score is None
    ):
        return None

    if (
        prediction.pred_home is None
        or prediction.pred_away is None
    ):
        return None

    actual_home = match.home_score
    actual_away = match.away_score

    predicted_home = prediction.pred_home
    predicted_away = prediction.pred_away

    # Exaktes Ergebnis
    if (
        predicted_home == actual_home
        and predicted_away == actual_away
    ):
        return 4

    actual_difference = (
        actual_home - actual_away
    )

    predicted_difference = (
        predicted_home - predicted_away
    )

    # Richtige Tordifferenz
    if predicted_difference == actual_difference:
        return 3

    def tendency(
        home_score: int,
        away_score: int,
    ) -> int:
        if home_score > away_score:
            return 1

        if home_score < away_score:
            return -1

        return 0

    # Richtige Tendenz
    if tendency(
        predicted_home,
        predicted_away,
    ) == tendency(
        actual_home,
        actual_away,
    ):
        return 2

    return 0


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
        .filter(
            match=match,
        )
        .only(
            "id",
            "match_id",
            "pred_home",
            "pred_away",
            "points",
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
        )

        return len(predictions)

    for prediction in predictions:
        prediction.points = (
            points_for_prediction(
                match,
                prediction,
            )
        )

    Prediction.objects.bulk_update(
        predictions,
        ["points"],
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