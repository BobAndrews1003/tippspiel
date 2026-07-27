from .models import (
    GroupMembership,
    GroupStanding,
)
from .standings import (
    rebuild_group_bonus_points,
    rebuild_group_standing,
)


def rebuild_group_standing_with_bonus_fallback(
    *,
    group_id: int,
) -> int:
    """
    Baut den Gesamtstand möglichst ohne erneute
    Bonusberechnung auf.

    Existiert für jedes aktuelle Mitglied bereits eine
    GroupStanding-Zeile, bleiben die vorberechneten
    Bonuspunkte erhalten.

    Fehlt mindestens eine Standing-Zeile, wird stattdessen
    ein vollständiger Bonus-Rebuild ausgeführt. Dadurch
    können die Tabellen auch aus unvollständigen
    vorberechneten Daten wiederhergestellt werden.
    """

    standing_user_ids = (
        GroupStanding.objects
        .filter(
            group_id=group_id,
        )
        .values(
            "user_id",
        )
    )

    missing_standing_exists = (
        GroupMembership.objects
        .filter(
            group_id=group_id,
        )
        .exclude(
            user_id__in=standing_user_ids,
        )
        .exists()
    )

    if missing_standing_exists:
        return rebuild_group_bonus_points(
            group_id=group_id,
        )

    return rebuild_group_standing(
        group_id=group_id,
    )
