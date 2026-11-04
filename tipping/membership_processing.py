from django.db import transaction

from .models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
)
from .standings import (
    rebuild_group_bonus_points,
    rebuild_group_timeline,
    rebuild_matchday_scores,
)


@transaction.atomic
def rebuild_group_after_membership_change(
    group_id: int,
) -> int:
    """
    Aktualisiert das vollständige vorberechnete Read Model
    einer Gruppe nach einem Beitritt, Austritt oder Wechsel
    einer Mitgliedschaft.

    Rückgabewert:
        Anzahl der aktuellen GroupStanding-Zeilen.
    """

    group = (
        Group.objects
        .only(
            "id",
            "tournament_id",
        )
        .filter(
            pk=group_id,
        )
        .first()
    )

    if group is None:
        return 0

    member_exists = (
        GroupMembership.objects
        .filter(
            group_id=group_id,
        )
        .exists()
    )

    if not member_exists:
        MatchdayScore.objects.filter(
            group_id=group_id,
        ).delete()

        GroupStanding.objects.filter(
            group_id=group_id,
        ).delete()

        return 0

    tournament_ids = group.selected_tournament_ids()
    result_events = list(
        Match.objects
        .filter(
            tournament_id__in=tournament_ids,
            home_score__isnull=False,
            away_score__isnull=False,
        )
        .exclude(
            matchday__isnull=True,
        )
        .values_list(
            "tournament_id",
            "matchday",
        )
        .distinct()
        .order_by("tournament_id", "matchday")
    )

    # Score-Zeilen von nicht mehr ausgewerteten oder
    # nicht mehr vorhandenen Spieltagen entfernen.
    if result_events:
        valid_events = set(result_events)
        obsolete_ids = [
            row.id
            for row in (
                MatchdayScore.objects
                .filter(group_id=group_id)
                .only("id", "tournament_id", "matchday")
            )
            if (row.tournament_id, row.matchday)
            not in valid_events
        ]

        if obsolete_ids:
            MatchdayScore.objects.filter(
                id__in=obsolete_ids,
            ).delete()

    else:
        MatchdayScore.objects.filter(
            group_id=group_id,
        ).delete()

    for tournament_id, matchday in result_events:
        rebuild_matchday_scores(
            group_id=group_id,
            matchday=matchday,
            tournament_id=tournament_id,
        )

    if result_events:
        rebuild_group_timeline(
            group_id=group_id,
            start_matchday=1,
        )

    return rebuild_group_bonus_points(
        group_id=group_id,
    )
