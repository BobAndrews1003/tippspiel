from django.db.models.signals import post_save
from django.dispatch import receiver

from .group_scoring import ensure_group_scoring_settings
from .models import Group


@receiver(
    post_save,
    sender=Group,
    dispatch_uid="tipping_create_default_group_scoring_settings",
)
def create_default_group_scoring_settings(
    sender,
    instance,
    created,
    **kwargs,
):
    if created:
        ensure_group_scoring_settings(instance)
