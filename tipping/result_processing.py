from django.db import transaction

from .models import (
    Group,
    Match,
    MatchdayScore,
)
from .scoring import recalculate_points_for_match
from .standings import (
    rebuild_group_bonus_points,
    rebuild_group_timeline,
    rebuild_matchday_scores,
)


def _matchday_has_results(
    *,
    tournament_id: int,
    matchday: int,
) -> bool:
    """
    Prüft, ob es an einem Spieltag mindestens ein
    vollständig ausgewertetes Spiel gibt.
    """

    return Match.objects.filter(
        tournament_id=tournament_id,
        matchday=matchday,
        home_score__isnull=False,
        away_score__isnull=False,
    ).exists()


@transaction.atomic
def process_match_change(
    *,
    match_id: int,
    previous_matchday: int | None = None,
) -> int:
    """
    Verarbeitet eine Ergebnis- oder Spieltagsänderung.

    Ablauf:
    1. Tipp-Punkte des Spiels neu berechnen.
    2. Betroffene Spieltagssummen aller Gruppen aktualisieren.
    3. Historische Ränge ab dem frühesten betroffenen
       Spieltag neu berechnen.
    4. Aktuelle Gruppenstände neu aufbauen.

    Rückgabewert:
        Anzahl der bearbeiteten Gruppen.
    """

    match = (
        Match.objects
        .select_for_update()
        .filter(
            pk=match_id,
        )
        .first()
    )

    if match is None:
        return 0

    # Prediction.points vollständig neu berechnen.
    recalculate_points_for_match(
        match,
    )

    affected_matchdays = {
        matchday
        for matchday in (
            previous_matchday,
            match.matchday,
        )
        if matchday is not None
    }

    # Spiele ohne Spieltag fließen nicht in die
    # Spieltags- und Ranglistenarchitektur ein.
    if not affected_matchdays:
        return 0

    # Jede Gruppe dieses Turniers ist betroffen.
    #
    # Auch wenn in einer Gruppe niemand dieses konkrete
    # Spiel getippt hat, muss dort gegebenenfalls eine
    # Spieltagszeile mit 0 Punkten angelegt werden.
    group_ids = list(
        Group.objects
        .filter(
            tournament_id=match.tournament_id,
            memberships__isnull=False,
        )
        .values_list(
            "id",
            flat=True,
        )
        .distinct()
        .order_by("id")
    )

    if not group_ids:
        return 0

    matchday_has_results = {
        matchday: _matchday_has_results(
            tournament_id=match.tournament_id,
            matchday=matchday,
        )
        for matchday in affected_matchdays
    }

    start_matchday = min(
        affected_matchdays
    )

    for group_id in group_ids:
        for matchday in sorted(
            affected_matchdays
        ):
            if matchday_has_results[
                matchday
            ]:
                rebuild_matchday_scores(
                    group_id=group_id,
                    matchday=matchday,
                )

            else:
                # Wurde das letzte Ergebnis dieses
                # Spieltags wieder entfernt, darf der
                # Spieltag nicht mehr ausgewertet bleiben.
                MatchdayScore.objects.filter(
                    group_id=group_id,
                    matchday=matchday,
                ).delete()

        # Eine Änderung an einem früheren Spieltag kann
        # alle späteren kumulierten Ränge verändern.
        rebuild_group_timeline(
            group_id=group_id,
            start_matchday=start_matchday,
        )

        rebuild_group_bonus_points(
        group_id=group_id,
)

    return len(group_ids)
