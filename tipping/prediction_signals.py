from django.db import transaction
from django.db.models.signals import (
    post_delete,
    post_save,
    pre_save,
)
from django.dispatch import receiver

from .models import Prediction
from .prediction_processing import (
    process_prediction_change,
    process_prediction_delete,
)


@receiver(
    pre_save,
    sender=Prediction,
    dispatch_uid=(
        "tipping_remember_previous_prediction_location"
    ),
)
def remember_previous_prediction_location(
    sender,
    instance,
    **kwargs,
):
    """
    Merkt sich die bisherige Gruppe und das bisherige
    Spiel einer bestehenden Prediction.
    """

    if not instance.pk:
        instance._previous_group_id = None
        instance._previous_match_id = None
        return

    previous_state = (
        sender.objects
        .filter(
            pk=instance.pk,
        )
        .values(
            "group_id",
            "match_id",
        )
        .first()
    )

    if previous_state is None:
        instance._previous_group_id = None
        instance._previous_match_id = None
        return

    instance._previous_group_id = (
        previous_state["group_id"]
    )

    instance._previous_match_id = (
        previous_state["match_id"]
    )


@receiver(
    post_save,
    sender=Prediction,
    dispatch_uid=(
        "tipping_process_prediction_save"
    ),
)
def process_after_prediction_save(
    sender,
    instance,
    **kwargs,
):
    """
    Prüft nach dem Commit, ob der Tipp zu einem bereits
    ausgewerteten Spiel gehört und aktualisiert dann das
    vorberechnete Read Model.
    """

    prediction_id = instance.pk

    previous_group_id = getattr(
        instance,
        "_previous_group_id",
        None,
    )

    previous_match_id = getattr(
        instance,
        "_previous_match_id",
        None,
    )

    def run_processing():
        process_prediction_change(
            prediction_id=prediction_id,
            previous_group_id=previous_group_id,
            previous_match_id=previous_match_id,
        )

    transaction.on_commit(
        run_processing
    )


def _is_direct_prediction_delete(
    origin,
) -> bool:
    """
    Direkte Prediction-Löschungen sollen verarbeitet werden.

    Kaskaden durch das Löschen eines Match, Group oder User
    werden übersprungen, weil diese Objekte eigene
    Verarbeitungspfade besitzen.
    """

    if origin is None:
        return True

    if isinstance(
        origin,
        Prediction,
    ):
        return True

    return (
        getattr(
            origin,
            "model",
            None,
        )
        is Prediction
    )


@receiver(
    post_delete,
    sender=Prediction,
    dispatch_uid=(
        "tipping_process_prediction_delete"
    ),
)
def process_after_prediction_delete(
    sender,
    instance,
    **kwargs,
):
    """
    Aktualisiert nach dem direkten Löschen eines Tipps
    die betroffene Gruppe.
    """

    origin = kwargs.get("origin")

    if not _is_direct_prediction_delete(
        origin
    ):
        return

    group_id = instance.group_id
    match_id = instance.match_id

    def run_processing():
        process_prediction_delete(
            group_id=group_id,
            match_id=match_id,
        )

    transaction.on_commit(
        run_processing
    )
