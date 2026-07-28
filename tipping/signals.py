from django.db import transaction
from django.db.models.signals import (
    post_delete,
    post_save,
    pre_save,
)
from django.dispatch import receiver

from .match_rebuild_routing import (
    route_match_change,
    route_match_delete,
)
from .models import Match


@receiver(
    pre_save,
    sender=Match,
    dispatch_uid="tipping_remember_match_state",
)
def remember_previous_match_state(
    sender,
    instance,
    **kwargs,
):
    """
    Merkt sich vor dem Speichern:

    - den bisherigen Spieltag,
    - ob sich Ergebnis oder relevanter Spieltag geändert haben.
    """

    if not instance.pk:
        instance._previous_matchday = None

        instance._standings_relevant_changed = (
            instance.home_score is not None
            and instance.away_score is not None
        )

        return

    previous_state = (
        sender.objects
        .filter(
            pk=instance.pk,
        )
        .values(
            "home_score",
            "away_score",
            "matchday",
        )
        .first()
    )

    if previous_state is None:
        instance._previous_matchday = None
        instance._standings_relevant_changed = True
        return

    previous_matchday = previous_state[
        "matchday"
    ]

    instance._previous_matchday = (
        previous_matchday
    )

    result_changed = (
        previous_state["home_score"]
        != instance.home_score
        or previous_state["away_score"]
        != instance.away_score
    )

    matchday_changed = (
        previous_matchday
        != instance.matchday
    )

    previous_had_result = (
        previous_state["home_score"]
        is not None
        and previous_state["away_score"]
        is not None
    )

    current_has_result = (
        instance.home_score is not None
        and instance.away_score is not None
    )

    relevant_matchday_change = (
        matchday_changed
        and (
            previous_had_result
            or current_has_result
        )
    )

    instance._standings_relevant_changed = (
        result_changed
        or relevant_matchday_change
    )


@receiver(
    post_save,
    sender=Match,
    dispatch_uid="tipping_process_match_change",
)
def process_match_after_relevant_change(
    sender,
    instance,
    **kwargs,
):
    """
    Startet die Ergebnisverarbeitung nach erfolgreichem
    Datenbank-Commit.
    """

    relevant_change = getattr(
        instance,
        "_standings_relevant_changed",
        False,
    )

    if not relevant_change:
        return

    match_id = instance.pk

    previous_matchday = getattr(
        instance,
        "_previous_matchday",
        None,
    )

    def run_processing():
        route_match_change(
            match_id=match_id,
            previous_matchday=previous_matchday,
        )

    transaction.on_commit(
        run_processing
    )


@receiver(
    post_delete,
    sender=Match,
    dispatch_uid="tipping_process_match_delete",
)
def process_after_match_delete(
    sender,
    instance,
    **kwargs,
):
    """
    Aktualisiert Spieltagssummen, historische Ränge und
    Gruppenstände nach dem Löschen eines ausgewerteten Spiels.

    Die zugehörigen Prediction-Zeilen wurden durch die
    Datenbankkaskade ebenfalls gelöscht.
    """

    tournament_id = instance.tournament_id
    matchday = instance.matchday

    had_result = (
        instance.home_score is not None
        and instance.away_score is not None
    )

    if (
        matchday is None
        or not had_result
    ):
        return

    def run_processing():
        route_match_delete(
            tournament_id=tournament_id,
            matchday=matchday,
            had_result=had_result,
        )

    transaction.on_commit(
        run_processing
    )
