from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from .models import (
    BonusPrediction,
    Group,
    GroupMembership,
    GroupStanding,
    MatchdayScore,
    Prediction,
)

from .bonus_scoring import (
    bonus_points_for_user,
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
def rebuild_group_bonus_points(
    group_id: int,
) -> int:
    """
    Berechnet die Bonuspunkte aller aktuellen Mitglieder
    einer Gruppe neu.

    Bonuspunkte werden unabhängig vom Freigabezeitpunkt
    vorberechnet. Die Views entscheiden, ob sie bereits
    angezeigt und in der sichtbaren Rangfolge berücksichtigt
    werden dürfen.

    Rückgabewert:
        Anzahl der aktualisierten GroupStanding-Zeilen.
    """

    group = (
        Group.objects
        .select_related("tournament")
        .get(
            pk=group_id,
        )
    )

    # Stellt sicher, dass jedes aktuelle Mitglied
    # eine GroupStanding-Zeile besitzt.
    rebuild_group_standing(
        group_id=group_id,
    )

    standings = list(
        GroupStanding.objects
        .select_for_update()
        .filter(
            group_id=group_id,
        )
        .order_by("user_id")
    )

    if not standings:
        return 0

    user_ids = [
        standing.user_id
        for standing in standings
    ]

    bonus_predictions = (
        BonusPrediction.objects
        .filter(
            group_id=group_id,
            tournament_id=group.tournament_id,
            user_id__in=user_ids,
        )
        .order_by(
            "user_id",
            "bonus_type",
        )
    )

    predictions_by_user = {}

    for prediction in bonus_predictions:
        predictions_by_user.setdefault(
            prediction.user_id,
            [],
        ).append(
            prediction
        )

    updated_at = timezone.now()

    for standing in standings:
        bonus_points = bonus_points_for_user(
            group.tournament,
            predictions_by_user.get(
                standing.user_id,
                [],
            ),
        )

        standing.bonus_points = bonus_points

        standing.total_points = (
            standing.match_points
            + bonus_points
        )

        standing.updated_at = updated_at

    GroupStanding.objects.bulk_update(
        standings,
        [
            "bonus_points",
            "total_points",
            "updated_at",
        ],
        batch_size=1000,
    )

    return len(standings)


@transaction.atomic
def rebuild_group_standing(
    group_id: int,
) -> int:
    """
    Baut den aktuellen Gesamtstand einer Gruppe neu auf.

    Berücksichtigt nur aktuelle Gruppenmitglieder.
    Vorhandene Bonuspunkte bleiben erhalten.
    """

    from django.db.models import Sum

    member_ids = list(
        GroupMembership.objects
        .filter(
            group_id=group_id,
        )
        .values_list(
            "user_id",
            flat=True,
        )
        .order_by("user_id")
    )

    if not member_ids:
        GroupStanding.objects.filter(
            group_id=group_id,
        ).delete()

        return 0

    # Entfernt Ranglistenzeilen von Nutzern,
    # die nicht mehr Mitglied der Gruppe sind.
    GroupStanding.objects.filter(
        group_id=group_id,
    ).exclude(
        user_id__in=member_ids,
    ).delete()

    score_rows = (
        MatchdayScore.objects
        .filter(
            group_id=group_id,
            user_id__in=member_ids,
        )
        .values("user_id")
        .annotate(
            match_points=Sum("points"),
            exact_predictions=Sum(
                "exact_predictions"
            ),
            matchday_wins=Max(
                "cumulative_matchday_wins"
            ),
        )
    )

    scores_by_user = {
        row["user_id"]: {
            "match_points": (
                row["match_points"]
                or 0
            ),
            "exact_predictions": (
                row["exact_predictions"]
                or 0
            ),
            "matchday_wins": (
                row["matchday_wins"]
                or 0
            ),
        }
        for row in score_rows
    }

    # Bonuspunkte werden bewahrt, weil diese Funktion
    # auch vor rebuild_group_bonus_points() aufgerufen
    # wird.
    bonus_by_user = dict(
        GroupStanding.objects
        .filter(
            group_id=group_id,
            user_id__in=member_ids,
        )
        .values_list(
            "user_id",
            "bonus_points",
        )
    )

    updated_at = timezone.now()
    standings = []

    for user_id in member_ids:
        score_data = scores_by_user.get(
            user_id,
            {},
        )

        match_points = score_data.get(
            "match_points",
            0,
        )

        exact_predictions = score_data.get(
            "exact_predictions",
            0,
        )

        matchday_wins = score_data.get(
            "matchday_wins",
            0,
        )

        bonus_points = (
            bonus_by_user.get(
                user_id,
                0,
            )
            or 0
        )

        standings.append(
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
                matchday_wins=matchday_wins,
                updated_at=updated_at,
            )
        )

    GroupStanding.objects.bulk_create(
        standings,
        batch_size=1000,
        update_conflicts=True,
        update_fields=[
            "match_points",
            "bonus_points",
            "total_points",
            "exact_predictions",
            "matchday_wins",
            "updated_at",
        ],
        unique_fields=[
            "group",
            "user",
        ],
    )

    return len(standings)


def _competition_ranks(
    user_ids,
    cumulative_points,
    cumulative_matchday_wins,
    username_by_id,
):
    """
    Berechnet Wettbewerbsränge anhand der kumulierten
    Punkte und der Spieltagssiege als Tiebreaker.

    Gleiche Punktzahlen und gleich viele Spieltagssiege
    erhalten denselben Rang.
    Der folgende Rang wird entsprechend übersprungen:

        1, 2, 2, 4

    Benutzername und Benutzer-ID dienen nur einer
    stabilen, reproduzierbaren Sortierung bei Gleichstand.
    """

    sorted_user_ids = sorted(
        user_ids,
        key=lambda user_id: (
            -cumulative_points.get(
                user_id,
                0,
            ),
            -cumulative_matchday_wins.get(
                user_id,
                0,
            ),
            (
                username_by_id.get(
                    user_id,
                    "",
                )
                or ""
            ).strip().lower(),
            user_id,
        ),
    )

    ranks = {}

    previous_ranking_key = None
    current_rank = 0

    for index, user_id in enumerate(
        sorted_user_ids,
        start=1,
    ):
        points = cumulative_points.get(
            user_id,
            0,
        )
        matchday_wins = (
            cumulative_matchday_wins.get(
                user_id,
                0,
            )
        )
        ranking_key = (
            points,
            matchday_wins,
        )

        if (
            previous_ranking_key is None
            or ranking_key
            != previous_ranking_key
        ):
            current_rank = index
            previous_ranking_key = ranking_key

        ranks[user_id] = current_rank

    return ranks


@transaction.atomic
def rebuild_group_timeline(
    group_id: int,
    start_matchday: int = 1,
) -> int:
    """
    Berechnet innerhalb einer Gruppe ab dem angegebenen
    Spieltag:

    - kumulierte Spielpunkte,
    - Rang nach diesem Spieltag,
    - Rangveränderung gegenüber dem vorherigen
      ausgewerteten Spieltag.

    Bei einem Teil-Rebuild werden die bereits gespeicherten
    kumulierten Punkte und Ränge des letzten früheren
    Spieltags als Ausgangsbasis verwendet. Dadurch müssen
    die historischen Score-Zeilen vor start_matchday nicht
    erneut geladen und durchlaufen werden.

    Bonuspunkte werden bewusst nicht einbezogen.

    Rückgabewert:
        Anzahl der aktualisierten MatchdayScore-Zeilen.
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
        .select_related(
            "user",
        )
        .only(
            "user_id",
            "user__username",
            "user__email",
        )
        .order_by(
            "user_id",
        )
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

    # Nur Score-Zeilen ab dem tatsächlich betroffenen
    # Spieltag laden.
    scores = list(
        MatchdayScore.objects
        .filter(
            group_id=group_id,
            user_id__in=user_ids,
            matchday__gte=start_matchday,
        )
        .only(
            "id",
            "group_id",
            "user_id",
            "matchday",
            "points",
            "exact_predictions",
            "cumulative_points",
            "cumulative_matchday_wins",
            "rank",
            "rank_change",
            "updated_at",
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

    # Für jeden betroffenen Spieltag muss jedes aktuelle
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
            .only(
                "id",
                "group_id",
                "user_id",
                "matchday",
                "points",
                "exact_predictions",
                "cumulative_points",
                "cumulative_matchday_wins",
                "rank",
                "rank_change",
                "updated_at",
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

    cumulative_matchday_wins = {
        user_id: 0
        for user_id in user_ids
    }

    previous_rank = {
        user_id: None
        for user_id in user_ids
    }

    # ----------------------------------------------------------
    # Ausgangsbasis eines Teil-Rebuilds
    #
    # Statt sämtliche früheren Spieltage erneut zu laden und
    # zu summieren, wird nur der letzte frühere Spieltag
    # benötigt.
    # ----------------------------------------------------------

    if start_matchday > 1:
        previous_matchday = (
            MatchdayScore.objects
            .filter(
                group_id=group_id,
                user_id__in=user_ids,
                matchday__lt=start_matchday,
            )
            .order_by(
                "-matchday",
            )
            .values_list(
                "matchday",
                flat=True,
            )
            .first()
        )

        if previous_matchday is not None:
            previous_rows = list(
                MatchdayScore.objects
                .filter(
                    group_id=group_id,
                    user_id__in=user_ids,
                    matchday=previous_matchday,
                )
                .only(
                    "user_id",
                    "cumulative_points",
                    "cumulative_matchday_wins",
                    "rank",
                )
                .order_by(
                    "user_id",
                )
            )

            previous_by_user = {
                row.user_id: row
                for row in previous_rows
            }

            baseline_is_complete = (
                len(previous_by_user)
                == len(user_ids)
                and all(
                    user_id in previous_by_user
                    and previous_by_user[
                        user_id
                    ].rank is not None
                    for user_id in user_ids
                )
            )

            if not baseline_is_complete:
                # Sicherheitsfallback bei unvollständigem
                # Read Model. Der vollständige Rebuild
                # entspricht dem bisherigen Verhalten.
                return rebuild_group_timeline(
                    group_id=group_id,
                    start_matchday=1,
                )

            cumulative_points = {
                user_id: (
                    previous_by_user[
                        user_id
                    ].cumulative_points
                    or 0
                )
                for user_id in user_ids
            }

            cumulative_matchday_wins = {
                user_id: (
                    previous_by_user[
                        user_id
                    ].cumulative_matchday_wins
                    or 0
                )
                for user_id in user_ids
            }

            previous_rank = {
                user_id: previous_by_user[
                    user_id
                ].rank
                for user_id in user_ids
            }

    changed_scores = []

    for matchday in matchdays:
        matchday_points = {}

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

            matchday_points[user_id] = (
                score.points
            )

        winning_points = max(
            matchday_points.values(),
            default=0,
        )

        for user_id in user_ids:
            if (
                matchday_points[user_id]
                == winning_points
            ):
                cumulative_matchday_wins[
                    user_id
                ] += 1

        current_ranks = _competition_ranks(
            user_ids=user_ids,
            cumulative_points=cumulative_points,
            cumulative_matchday_wins=(
                cumulative_matchday_wins
            ),
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

            score.cumulative_matchday_wins = (
                cumulative_matchday_wins[
                    user_id
                ]
            )

            score.rank = new_rank

            score.rank_change = (
                None
                if old_rank is None
                else old_rank - new_rank
            )

            score.updated_at = now

            changed_scores.append(
                score
            )

        previous_rank = current_ranks

    MatchdayScore.objects.bulk_update(
        changed_scores,
        [
            "cumulative_points",
            "cumulative_matchday_wins",
            "rank",
            "rank_change",
            "updated_at",
        ],
        batch_size=1000,
    )

    return len(changed_scores)
