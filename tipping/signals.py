from django.db import transaction
from django.db.models.signals import (
    post_save,
    pre_save,
)
from django.dispatch import receiver

from .models import Match
from .result_processing import (
    process_match_change,
)


@receiver(
    pre_save,
    sender=Match,
)
def remember_previous_match_state(
    sender,
    instance,
    **kwargs,
):
    """
    Merkt sich vor dem Speichern:

    - das bisherige Ergebnis,
    - den bisherigen Spieltag,
    - ob eine ranglistenrelevante Änderung vorliegt.
    """

    if not instance.pk:
        instance._previous_matchday = None

        # Ein neu erstelltes Spiel muss nur verarbeitet
        # werden, wenn bereits ein Ergebnis vorliegt.
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

    # Eine Spieltagsänderung ist nur relevant,
    # wenn das Spiel bereits ausgewertet war oder
    # aktuell ausgewertet ist.
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
)
def process_match_after_relevant_change(
    sender,
    instance,
    created,
    **kwargs,
):
    """
    Startet die vollständige Verarbeitung erst nach
    erfolgreichem Datenbank-Commit.
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

    transaction.on_commit(
        lambda: process_match_change(
            match_id=match_id,
            previous_matchday=previous_matchday,
        )
    )
