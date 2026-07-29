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

    result_matchdays = list(
        Match.objects
        .filter(
            tournament_id=group.tournament_id,
            home_score__isnull=False,
            away_score__isnull=False,
        )
        .exclude(
            matchday__isnull=True,
        )
        .values_list(
            "matchday",
            flat=True,
        )
        .distinct()
        .order_by("matchday")
    )

    # Score-Zeilen von nicht mehr ausgewerteten oder
    # nicht mehr vorhandenen Spieltagen entfernen.
    if result_matchdays:
        MatchdayScore.objects.filter(
            group_id=group_id,
        ).exclude(
            matchday__in=result_matchdays,
        ).delete()

    else:
        MatchdayScore.objects.filter(
            group_id=group_id,
        ).delete()

    for matchday in result_matchdays:
        rebuild_matchday_scores(
            group_id=group_id,
            matchday=matchday,
        )

    if result_matchdays:
        rebuild_group_timeline(
            group_id=group_id,
            start_matchday=result_matchdays[0],
        )

    return rebuild_group_bonus_points(
        group_id=group_id,
    )
