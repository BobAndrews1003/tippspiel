from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Tournament
from .tournament_stages import ensure_default_stages


@receiver(
    post_save,
    sender=Tournament,
    dispatch_uid="tipping_create_default_tournament_stages",
)
def create_default_tournament_stages(
    sender,
    instance,
    created,
    **kwargs,
):
    if created:
        ensure_default_stages(instance)
