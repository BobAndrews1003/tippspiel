from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    Group,
    GroupMembership,
    GroupStanding,
    MatchdayScore,
    Prediction,
)

@transaction.atomic
def rebuild_matchday_scores(
    group_id: int,
    matchday: int,
) -> int:
    """
    Berechnet die Spieltagssumme aller aktuellen Mitglieder
    einer bestimmten Gruppe neu.

    Die Funktion liest ausschließlich Tipps der angegebenen
    Gruppe. Daten anderer Gruppen werden nicht berücksichtigt.

    Rückgabewert:
        Anzahl der erzeugten oder aktualisierten
        MatchdayScore-Zeilen.
    """

    if matchday < 1:
        raise ValueError(
            "matchday muss mindestens 1 sein."
        )

    group = (
        Group.objects
        .only(
            "id",
            "tournament_id",
        )
        .get(
            pk=group_id,
        )
    )

    # Nur aktuelle Mitglieder dieser Gruppe.
    user_ids = list(
        GroupMembership.objects
        .filter(
            group_id=group_id,
        )
        .order_by("user_id")
        .values_list(
            "user_id",
            flat=True,
        )
    )

    # Besitzt die Gruppe keine Mitglieder mehr,
    # dürfen auch keine vorberechneten Zeilen bleiben.
    if not user_ids:
        MatchdayScore.objects.filter(
            group_id=group_id,
            matchday=matchday,
        ).delete()

        return 0

    # Alte Score-Zeilen ausgeschiedener Mitglieder entfernen.
    MatchdayScore.objects.filter(
        group_id=group_id,
        matchday=matchday,
    ).exclude(
        user_id__in=user_ids,
    ).delete()

    # Die Punkte werden ausschließlich aus bereits
    # ausgewerteten Tipps dieser Gruppe summiert.
    aggregates = (
        Prediction.objects
        .filter(
            group_id=group_id,
            user_id__in=user_ids,
            match__tournament_id=(
                group.tournament_id
            ),
            match__matchday=matchday,
            match__home_score__isnull=False,
            match__away_score__isnull=False,
            points__isnull=False,
        )
        .values(
            "user_id",
        )
        .annotate(
            total_points=Sum(
                "points",
                default=0,
            ),
            exact_predictions=Count(
                "id",
                filter=Q(
                    points=4,
                ),
            ),
        )
    )

    aggregates_by_user = {
        row["user_id"]: row
        for row in aggregates
    }

    updated_at = timezone.now()
    score_rows = []

    # Für jedes Gruppenmitglied wird eine Zeile angelegt.
    # Nutzer ohne gewerteten Tipp erhalten 0 Punkte.
    for user_id in user_ids:
        values = aggregates_by_user.get(
            user_id,
        )

        score_rows.append(
            MatchdayScore(
                group_id=group_id,
                user_id=user_id,
                matchday=matchday,
                points=(
                    values["total_points"]
                    if values
                    else 0
                ),
                exact_predictions=(
                    values["exact_predictions"]
                    if values
                    else 0
                ),
                updated_at=updated_at,
            )
        )

    MatchdayScore.objects.bulk_create(
        score_rows,
        update_conflicts=True,
        unique_fields=[
            "group",
            "user",
            "matchday",
        ],
        update_fields=[
            "points",
            "exact_predictions",
            "updated_at",
        ],
        batch_size=1000,
    )

    return len(score_rows)

@transaction.atomic
def rebuild_group_standing(
    group_id: int,
) -> int:
    """
    Berechnet die aktuelle Gesamttabelle einer Gruppe neu.

    Die Spielpunkte und die Anzahl exakter Tipps werden
    aus MatchdayScore aggregiert.

    Bereits gespeicherte Bonuspunkte bleiben erhalten,
    bis eine eigene Bonusauswertung eingeführt wird.

    Rückgabewert:
        Anzahl der erzeugten oder aktualisierten
        GroupStanding-Zeilen.
    """

    # Prüft gleichzeitig, ob die Gruppe existiert.
    Group.objects.only(
        "id",
    ).get(
        pk=group_id,
    )

    user_ids = list(
        GroupMembership.objects
        .filter(
            group_id=group_id,
        )
        .order_by("user_id")
        .values_list(
            "user_id",
            flat=True,
        )
    )

    # Keine Mitglieder bedeutet:
    # Es darf auch keine Rangliste mehr geben.
    if not user_ids:
        GroupStanding.objects.filter(
            group_id=group_id,
        ).delete()

        return 0

    # Alte Ranglistenzeilen ausgeschiedener
    # Mitglieder entfernen.
    GroupStanding.objects.filter(
        group_id=group_id,
    ).exclude(
        user_id__in=user_ids,
    ).delete()

    aggregates = (
        MatchdayScore.objects
        .filter(
            group_id=group_id,
            user_id__in=user_ids,
        )
        .values(
            "user_id",
        )
        .annotate(
            match_points=Sum(
                "points",
                default=0,
            ),
            exact_predictions=Sum(
                "exact_predictions",
                default=0,
            ),
        )
    )

    aggregates_by_user = {
        row["user_id"]: row
        for row in aggregates
    }

    # Bonuspunkte werden momentan noch nicht
    # automatisch berechnet. Bereits vorhandene
    # Werte dürfen beim Rebuild nicht verloren gehen.
    existing_bonus_points = dict(
        GroupStanding.objects
        .filter(
            group_id=group_id,
            user_id__in=user_ids,
        )
        .values_list(
            "user_id",
            "bonus_points",
        )
    )

    updated_at = timezone.now()
    standing_rows = []

    for user_id in user_ids:
        values = aggregates_by_user.get(
            user_id,
        )

        match_points = (
            values["match_points"]
            if values
            else 0
        )

        exact_predictions = (
            values["exact_predictions"]
            if values
            else 0
        )

        bonus_points = (
            existing_bonus_points.get(
                user_id,
                0,
            )
        )

        standing_rows.append(
            GroupStanding(
                group_id=group_id,
                user_id=user_id,
                match_points=match_points,
                bonus_points=bonus_points,
                total_points=(
                    match_points
                    + bonus_points
                ),
                exact_predictions=(
                    exact_predictions
                ),
                updated_at=updated_at,
            )
        )

    GroupStanding.objects.bulk_create(
        standing_rows,
        update_conflicts=True,
        unique_fields=[
            "group",
            "user",
        ],
        update_fields=[
            "match_points",
            "bonus_points",
            "total_points",
            "exact_predictions",
            "updated_at",
        ],
        batch_size=1000,
    )

    return len(standing_rows)

def _competition_ranks(
    user_ids: list[int],
    cumulative_points: dict[int, int],
    username_by_id: dict[int, str],
) -> dict[int, int]:
    """
    Erstellt Wettbewerbsränge:

    Punkte:
        10, 8, 8, 5

    Ränge:
        1, 2, 2, 4
    """

    sorted_user_ids = sorted(
        user_ids,
        key=lambda user_id: (
            -cumulative_points[user_id],
            username_by_id[user_id],
            user_id,
        ),
    )

    ranks = {}
    current_rank = 0
    previous_points = None

    for position, user_id in enumerate(
        sorted_user_ids,
        start=1,
    ):
        user_points = cumulative_points[
            user_id
        ]

        if (
            previous_points is None
            or user_points != previous_points
        ):
            current_rank = position
            previous_points = user_points

        ranks[user_id] = current_rank

    return ranks


@transaction.atomic
def rebuild_group_timeline(
    group_id: int,
    start_matchday: int = 1,
) -> int:
    """
    Berechnet innerhalb einer Gruppe für jeden Spieltag:

    - kumulierte Spielpunkte,
    - Rang nach diesem Spieltag,
    - Rangveränderung gegenüber dem vorherigen
      ausgewerteten Spieltag.

    Bonuspunkte werden bewusst nicht einbezogen, weil die
    bestehende historische Ranglogik ebenfalls ausschließlich
    normale Spielpunkte verwendet.

    Der Rückgabewert ist die Anzahl der aktualisierten
    MatchdayScore-Zeilen.
    """

    if start_matchday < 1:
        raise ValueError(
            "start_matchday muss mindestens 1 sein."
        )

    Group.objects.only(
        "id",
    ).get(
        pk=group_id,
    )

    memberships = list(
        GroupMembership.objects
        .filter(
            group_id=group_id,
        )
        .select_related("user")
        .order_by("user_id")
    )

    user_ids = [
        membership.user_id
        for membership in memberships
    ]

    if not user_ids:
        MatchdayScore.objects.filter(
            group_id=group_id,
        ).delete()

        return 0

    # Historische Zeilen ehemaliger Mitglieder entfernen.
    MatchdayScore.objects.filter(
        group_id=group_id,
    ).exclude(
        user_id__in=user_ids,
    ).delete()

    username_by_id = {
        membership.user_id: (
            membership.user.get_username()
            or membership.user.email
            or f"user-{membership.user_id}"
        ).strip().lower()
        for membership in memberships
    }

    scores = list(
        MatchdayScore.objects
        .filter(
            group_id=group_id,
            user_id__in=user_ids,
        )
        .order_by(
            "matchday",
            "user_id",
        )
    )

    if not scores:
        return 0

    matchdays = sorted(
        {
            score.matchday
            for score in scores
        }
    )

    # Für jeden vorhandenen Spieltag muss jedes aktuelle
    # Gruppenmitglied eine Score-Zeile besitzen.
    existing_keys = {
        (
            score.user_id,
            score.matchday,
        )
        for score in scores
    }

    now = timezone.now()

    missing_rows = [
        MatchdayScore(
            group_id=group_id,
            user_id=user_id,
            matchday=matchday,
            points=0,
            exact_predictions=0,
            cumulative_points=0,
            rank=None,
            rank_change=None,
            updated_at=now,
        )
        for matchday in matchdays
        for user_id in user_ids
        if (
            user_id,
            matchday,
        ) not in existing_keys
    ]

    if missing_rows:
        MatchdayScore.objects.bulk_create(
            missing_rows,
            ignore_conflicts=True,
            batch_size=1000,
        )

        scores = list(
            MatchdayScore.objects
            .filter(
                group_id=group_id,
                user_id__in=user_ids,
                matchday__in=matchdays,
            )
            .order_by(
                "matchday",
                "user_id",
            )
        )

    score_by_user_matchday = {
        (
            score.user_id,
            score.matchday,
        ): score
        for score in scores
    }

    cumulative_points = {
        user_id: 0
        for user_id in user_ids
    }

    # Bei einer Teilneuberechnung werden die Punkte vor dem
    # Startspieltag als Ausgangsbasis geladen.
    previous_matchdays = [
        matchday
        for matchday in matchdays
        if matchday < start_matchday
    ]

    for matchday in previous_matchdays:
        for user_id in user_ids:
            score = score_by_user_matchday[
                (
                    user_id,
                    matchday,
                )
            ]

            cumulative_points[
                user_id
            ] += score.points

    previous_rank = {
        user_id: None
        for user_id in user_ids
    }

    # Der Rang vor dem Startspieltag dient als Vergleich für
    # die erste neu berechnete Rangveränderung.
    if previous_matchdays:
        previous_rank = _competition_ranks(
            user_ids=user_ids,
            cumulative_points=cumulative_points,
            username_by_id=username_by_id,
        )

    affected_matchdays = [
        matchday
        for matchday in matchdays
        if matchday >= start_matchday
    ]

    if not affected_matchdays:
        return 0

    changed_scores = []

    for matchday in affected_matchdays:
        for user_id in user_ids:
            score = score_by_user_matchday[
                (
                    user_id,
                    matchday,
                )
            ]

            cumulative_points[
                user_id
            ] += score.points

        current_ranks = _competition_ranks(
            user_ids=user_ids,
            cumulative_points=cumulative_points,
            username_by_id=username_by_id,
        )

        for user_id in user_ids:
            score = score_by_user_matchday[
                (
                    user_id,
                    matchday,
                )
            ]

            old_rank = previous_rank[
                user_id
            ]

            new_rank = current_ranks[
                user_id
            ]

            score.cumulative_points = (
                cumulative_points[user_id]
            )

            score.rank = new_rank

            score.rank_change = (
                None
                if old_rank is None
                else old_rank - new_rank
            )

            score.updated_at = now

            changed_scores.append(score)

        previous_rank = current_ranks

    MatchdayScore.objects.bulk_update(
        changed_scores,
        [
            "cumulative_points",
            "rank",
            "rank_change",
            "updated_at",
        ],
        batch_size=1000,
    )

    return len(changed_scores)