from django.db import transaction

from .models import (
    Group,
    Match,
    MatchdayScore,
)
from .scoring import (
    recalculate_points_for_match,
)
from .standing_refresh import (
    rebuild_group_standing_with_bonus_fallback,
)
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


def _get_tournament_group_ids(
    tournament_id: int,
    group_ids=None,
) -> list[int]:
    """
    Liefert Gruppen des Turniers mit mindestens einem
    aktuellen Mitglied.

    Eine leere Gruppenauswahl bedeutet: alle Gruppen.
    """

    queryset = (
        Group.objects
        .filter(
            tournament_id=tournament_id,
            memberships__isnull=False,
            memberships__is_active=True,
        )
    )

    if group_ids:
        queryset = queryset.filter(
            pk__in=group_ids,
        )

    return list(
        queryset
        .values_list(
            "id",
            flat=True,
        )
        .distinct()
        .order_by("id")
    )


def _rebuild_affected_matchdays(
    *,
    tournament_id: int,
    affected_matchdays: set[int],
    rebuild_bonus: bool,
    group_ids=None,
) -> int:
    """
    Aktualisiert die vorberechneten Tabellen aller Gruppen
    eines Turniers für die angegebenen Spieltage.
    """

    if not affected_matchdays:
        return 0

    group_ids = _get_tournament_group_ids(
        tournament_id,
        group_ids=group_ids,
    )

    if not group_ids:
        return 0

    matchday_has_results = {
        matchday: _matchday_has_results(
            tournament_id=tournament_id,
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
                # Existiert kein ausgewertetes Spiel mehr,
                # darf dieser Spieltag nicht länger im
                # vorberechneten Read Model bleiben.
                MatchdayScore.objects.filter(
                    group_id=group_id,
                    matchday=matchday,
                ).delete()

        # Eine Änderung an einem früheren Spieltag kann
        # die kumulierten Punkte und Ränge aller späteren
        # Spieltage verändern.
        rebuild_group_timeline(
            group_id=group_id,
            start_matchday=start_matchday,
        )

        if rebuild_bonus:
            # Ein ausdrücklich angeforderter vollständiger
            # Rebuild berechnet auch die Bonuspunkte neu.
            rebuild_group_bonus_points(
                group_id=group_id,
            )

        else:
            # Der normale Signalpfad bewahrt vorhandene
            # Bonuspunkte. Fehlen Standing-Zeilen, wird
            # automatisch auf einen vollständigen
            # Bonus-Rebuild zurückgefallen.
            rebuild_group_standing_with_bonus_fallback(
                group_id=group_id,
            )

    return len(group_ids)


@transaction.atomic
def process_match_change(
    *,
    match_id: int,
    previous_matchday: int | None = None,
    rebuild_bonus: bool = True,
) -> int:
    """
    Verarbeitet eine Ergebnis- oder Spieltagsänderung.

    Ablauf:
    1. Tipp-Punkte des Spiels neu berechnen.
    2. Betroffene Spieltagssummen aktualisieren.
    3. Historische Ränge neu aufbauen.
    4. Aktuelle Gruppenstände aktualisieren.
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

    return _rebuild_affected_matchdays(
        tournament_id=match.tournament_id,
        affected_matchdays=affected_matchdays,
        rebuild_bonus=rebuild_bonus,
    )


@transaction.atomic
def process_match_delete(
    *,
    tournament_id: int,
    matchday: int | None,
    had_result: bool,
) -> int:
    """
    Aktualisiert das Read Model nach dem Löschen eines Spiels.

    Das Match selbst existiert zu diesem Zeitpunkt nicht mehr.
    Deshalb werden Turnier, Spieltag und Ergebnisstatus bereits
    vom Löschsignal übergeben.

    Ein nicht ausgewertetes Spiel beeinflusst die Ranglisten
    nicht und erfordert daher keinen Rebuild.
    """

    if (
        matchday is None
        or not had_result
    ):
        return 0

    return _rebuild_affected_matchdays(
        tournament_id=tournament_id,
        affected_matchdays={
            matchday,
        },
        rebuild_bonus=False,
    )


@transaction.atomic
def process_queued_tournament_rebuild(
    *,
    tournament_id: int,
    affected_matchdays: list[int],
    match_ids: list[int] | None = None,
    group_ids: list[int] | None = None,
    rebuild_bonus: bool = False,
) -> int:
    """
    Verarbeitet einen dauerhaften Ranglistenauftrag.

    Eine leere group_ids-Liste bedeutet, dass alle Gruppen
    des Turniers aktualisiert werden.
    """

    normalized_matchdays = set()

    for raw_matchday in affected_matchdays:
        try:
            matchday = int(raw_matchday)

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "Alle betroffenen Spieltage müssen "
                "ganze Zahlen sein."
            ) from exc

        if matchday < 1:
            raise ValueError(
                "Betroffene Spieltage müssen "
                "mindestens 1 sein."
            )

        normalized_matchdays.add(matchday)

    if not normalized_matchdays:
        return 0

    normalized_match_ids = set()

    for raw_match_id in match_ids or []:
        try:
            match_id = int(raw_match_id)

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "Alle Match-IDs müssen ganze Zahlen sein."
            ) from exc

        if match_id < 1:
            raise ValueError(
                "Match-IDs müssen mindestens 1 sein."
            )

        normalized_match_ids.add(match_id)

    normalized_group_ids = set()

    for raw_group_id in group_ids or []:
        try:
            group_id = int(raw_group_id)

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "Alle Gruppen-IDs müssen ganze Zahlen sein."
            ) from exc

        if group_id < 1:
            raise ValueError(
                "Gruppen-IDs müssen mindestens 1 sein."
            )

        normalized_group_ids.add(group_id)

    matches = list(
        Match.objects
        .select_for_update()
        .filter(
            tournament_id=tournament_id,
            pk__in=normalized_match_ids,
        )
        .order_by("id")
    )

    for match in matches:
        recalculate_points_for_match(match)

    return _rebuild_affected_matchdays(
        tournament_id=tournament_id,
        affected_matchdays=normalized_matchdays,
        rebuild_bonus=rebuild_bonus,
        group_ids=normalized_group_ids,
    )
