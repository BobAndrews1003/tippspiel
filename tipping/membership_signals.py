from django.db import transaction
from django.db.models.signals import (
    post_delete,
    post_save,
    pre_save,
)
from django.dispatch import receiver

from .membership_processing import (
    rebuild_group_after_membership_change,
)
from .models import GroupMembership
from .signal_control import (
    read_model_delete_signals_suppressed,
)


@receiver(
    pre_save,
    sender=GroupMembership,
    dispatch_uid=(
        "tipping_remember_previous_membership_group"
    ),
)
def remember_previous_membership_group(
    sender,
    instance,
    **kwargs,
):
    """
    Merkt sich bei einer bestehenden Mitgliedschaft
    die bisherige Gruppe.
    """

    if not instance.pk:
        instance._previous_group_id = None
        return

    instance._previous_group_id = (
        sender.objects
        .filter(
            pk=instance.pk,
        )
        .values_list(
            "group_id",
            flat=True,
        )
        .first()
    )


@receiver(
    post_save,
    sender=GroupMembership,
    dispatch_uid=(
        "tipping_membership_saved_read_model"
    ),
)
def rebuild_after_membership_save(
    sender,
    instance,
    **kwargs,
):
    """
    Aktualisiert die neue und gegebenenfalls auch
    die bisherige Gruppe.
    """

    group_ids = {
        instance.group_id,
        getattr(
            instance,
            "_previous_group_id",
            None,
        ),
    }

    group_ids.discard(None)

    ordered_group_ids = tuple(
        sorted(group_ids)
    )

    def run_rebuilds():
        for group_id in ordered_group_ids:
            rebuild_group_after_membership_change(
                group_id=group_id,
            )

    transaction.on_commit(
        run_rebuilds
    )


def _is_direct_membership_delete(
    origin,
) -> bool:
    """
    Direkte Löschungen einer Mitgliedschaft werden
    verarbeitet.

    Kaskaden durch das Löschen eines Users oder einer
    Gruppe besitzen einen anderen Ursprung und benötigen
    einen eigenen konsolidierten Verarbeitungspfad.
    """

    if origin is None:
        return True

    if isinstance(
        origin,
        GroupMembership,
    ):
        return True

    return (
        getattr(
            origin,
            "model",
            None,
        )
        is GroupMembership
    )


@receiver(
    post_delete,
    sender=GroupMembership,
    dispatch_uid=(
        "tipping_membership_deleted_read_model"
    ),
)
def rebuild_after_membership_delete(
    sender,
    instance,
    **kwargs,
):
    """
    Entfernt die vorberechneten Daten des ausgeschiedenen
    Mitglieds und berechnet die Ränge der verbleibenden
    Mitglieder neu.
    """

    if read_model_delete_signals_suppressed():
        return

    origin = kwargs.get("origin")

    if not _is_direct_membership_delete(
        origin
    ):
        return

    group_id = instance.group_id

    transaction.on_commit(
        lambda group_id=group_id: (
            rebuild_group_after_membership_change(
                group_id=group_id,
            )
        )
    )
