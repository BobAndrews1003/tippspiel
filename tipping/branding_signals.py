from django.db import transaction
from django.db.models.signals import (
    post_delete,
    post_save,
    pre_save,
)
from django.dispatch import receiver

from .models import GroupBranding


BRANDING_IMAGE_FIELDS = (
    "logo",
    "hero_image",
)


def _delete_after_commit(
    *,
    storage,
    name: str,
) -> None:
    if not name:
        return

    transaction.on_commit(
        lambda: storage.delete(name)
    )


@receiver(
    pre_save,
    sender=GroupBranding,
    dispatch_uid="tipping_remember_previous_group_logo",
)
def remember_previous_group_logo(
    sender,
    instance,
    **kwargs,
):
    instance._previous_branding_images = {}

    if not instance.pk:
        return

    previous = (
        sender.objects
        .only(*BRANDING_IMAGE_FIELDS)
        .filter(pk=instance.pk)
        .first()
    )

    if not previous:
        return

    for field_name in BRANDING_IMAGE_FIELDS:
        image = getattr(previous, field_name)

        if image:
            instance._previous_branding_images[field_name] = (
                image.name,
                image.storage,
            )


@receiver(
    post_save,
    sender=GroupBranding,
    dispatch_uid="tipping_delete_replaced_group_logo",
)
def delete_replaced_group_logo(
    sender,
    instance,
    **kwargs,
):
    previous_images = getattr(
        instance,
        "_previous_branding_images",
        {},
    )

    for field_name, (
        previous_name,
        storage,
    ) in previous_images.items():
        current_image = getattr(instance, field_name)
        current_name = (
            current_image.name
            if current_image
            else ""
        )

        if previous_name == current_name:
            continue

        _delete_after_commit(
            storage=storage,
            name=previous_name,
        )


@receiver(
    post_delete,
    sender=GroupBranding,
    dispatch_uid="tipping_delete_removed_group_logo",
)
def delete_removed_group_logo(
    sender,
    instance,
    **kwargs,
):
    for field_name in BRANDING_IMAGE_FIELDS:
        image = getattr(instance, field_name)

        if image:
            _delete_after_commit(
                storage=image.storage,
                name=image.name,
            )
