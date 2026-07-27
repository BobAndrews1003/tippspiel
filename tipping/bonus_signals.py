from django.db import transaction
from django.db.models.signals import (
    post_delete,
    post_save,
    pre_save,
)
from django.dispatch import receiver

from .bonus_processing import (
    rebuild_bonus_for_group_id,
    rebuild_bonus_for_tournament_id,
)
from .models import (
    BonusPrediction,
    Tournament,
)


BONUS_RESULT_FIELDS = {
    "autumn_champion",
    "champion",
    "first_coach_sacked",
    "top_scorer",
    "relegated_teams",
}


@receiver(
    post_save,
    sender=BonusPrediction,
    dispatch_uid="tipping_bonus_prediction_saved",
)
def rebuild_bonus_after_prediction_save(
    sender,
    instance,
    **kwargs,
):
    """
    Aktualisiert die betreffende Gruppe nach dem Erstellen
    oder Ändern eines Bonustipps.
    """

    group_id = instance.group_id

    transaction.on_commit(
        lambda group_id=group_id: (
            rebuild_bonus_for_group_id(
                group_id=group_id,
            )
        )
    )


@receiver(
    post_delete,
    sender=BonusPrediction,
    dispatch_uid="tipping_bonus_prediction_deleted",
)
def rebuild_bonus_after_prediction_delete(
    sender,
    instance,
    **kwargs,
):
    """
    Aktualisiert die betreffende Gruppe nach dem Löschen
    eines Bonustipps.
    """

    group_id = instance.group_id

    transaction.on_commit(
        lambda group_id=group_id: (
            rebuild_bonus_for_group_id(
                group_id=group_id,
            )
        )
    )


@receiver(
    pre_save,
    sender=Tournament,
    dispatch_uid="tipping_remember_bonus_results",
)
def remember_previous_bonus_results(
    sender,
    instance,
    **kwargs,
):
    """
    Prüft, ob sich eines der offiziellen Bonusresultate
    geändert hat.
    """

    if not instance.pk:
        instance._bonus_results_changed = False
        return

    update_fields = kwargs.get(
        "update_fields"
    )

    if (
        update_fields is not None
        and not BONUS_RESULT_FIELDS.intersection(
            update_fields
        )
    ):
        instance._bonus_results_changed = False
        return

    previous_results = (
        sender.objects
        .filter(
            pk=instance.pk,
        )
        .values(
            *BONUS_RESULT_FIELDS,
        )
        .first()
    )

    if previous_results is None:
        instance._bonus_results_changed = False
        return

    instance._bonus_results_changed = any(
        previous_results[field]
        != getattr(instance, field)
        for field in BONUS_RESULT_FIELDS
    )


@receiver(
    post_save,
    sender=Tournament,
    dispatch_uid="tipping_tournament_bonus_results_saved",
)
def rebuild_bonus_after_tournament_save(
    sender,
    instance,
    **kwargs,
):
    """
    Aktualisiert alle Gruppen des Turniers, wenn sich
    offizielle Bonusresultate geändert haben.
    """

    changed = getattr(
        instance,
        "_bonus_results_changed",
        False,
    )

    if not changed:
        return

    tournament_id = instance.pk

    transaction.on_commit(
        lambda tournament_id=tournament_id: (
            rebuild_bonus_for_tournament_id(
                tournament_id=tournament_id,
            )
        )
    )
