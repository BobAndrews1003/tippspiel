from django.db import transaction
from django.db.models.signals import (
    post_save,
    pre_save,
)
from django.dispatch import receiver

from .models import Match
from .scoring import (
    recalculate_points_for_match_id,
)


@receiver(
    pre_save,
    sender=Match,
)
def remember_previous_match_result(
    sender,
    instance,
    **kwargs,
):
    """
    Speichert vor dem Speichern, ob sich das Ergebnis
    des Spiels verändert hat.
    """

    if not instance.pk:
        instance._result_changed = True
        return

    previous_result = (
        sender.objects
        .filter(
            pk=instance.pk,
        )
        .values(
            "home_score",
            "away_score",
        )
        .first()
    )

    if previous_result is None:
        instance._result_changed = True
        return

    instance._result_changed = (
        previous_result["home_score"]
        != instance.home_score
        or previous_result["away_score"]
        != instance.away_score
    )


@receiver(
    post_save,
    sender=Match,
)
def recalculate_predictions_after_result_change(
    sender,
    instance,
    created,
    **kwargs,
):
    """
    Berechnet Tipp-Punkte nach einer Ergebnisänderung.

    transaction.on_commit() stellt sicher, dass erst nach
    erfolgreichem Speichern des Spiels gerechnet wird.
    """

    result_changed = getattr(
        instance,
        "_result_changed",
        created,
    )

    if not result_changed:
        return

    match_id = instance.pk

    transaction.on_commit(
        lambda: recalculate_points_for_match_id(
            match_id
        )
    )