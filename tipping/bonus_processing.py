from django.db import transaction

from .models import (
    Group,
    Tournament,
)
from .standings import (
    rebuild_group_bonus_points,
)


@transaction.atomic
def rebuild_bonus_for_group_id(
    group_id: int,
) -> int:
    """
    Aktualisiert die Bonuspunkte einer Gruppe.

    Existiert die Gruppe nicht mehr, wird die Verarbeitung
    ohne Fehler beendet.
    """

    if not Group.objects.filter(
        pk=group_id,
    ).exists():
        return 0

    return rebuild_group_bonus_points(
        group_id=group_id,
    )


@transaction.atomic
def rebuild_bonus_for_tournament_id(
    tournament_id: int,
) -> int:
    """
    Aktualisiert die Bonuspunkte aller Gruppen eines
    Turniers.

    Rückgabewert:
        Anzahl der verarbeiteten Gruppen.
    """

    if not Tournament.objects.filter(
        pk=tournament_id,
    ).exists():
        return 0

    group_ids = list(
        Group.objects
        .filter(
            tournament_id=tournament_id,
            memberships__isnull=False,
            memberships__is_active=True,
        )
        .values_list(
            "id",
            flat=True,
        )
        .distinct()
        .order_by("id")
    )

    for group_id in group_ids:
        rebuild_group_bonus_points(
            group_id=group_id,
        )

    return len(group_ids)
