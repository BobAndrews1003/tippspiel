from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import AccountRetentionNotice


@receiver(
    user_logged_in,
    dispatch_uid="tipping_clear_account_retention_notice_on_login",
)
def clear_account_retention_notice_on_login(
    sender,
    request,
    user,
    **kwargs,
):
    """
    Ein erfolgreicher Login beendet den aktuellen Warnzyklus.

    Der von Django aktualisierte last_login-Zeitpunkt startet bei
    späterer erneuter Inaktivität einen vollständig neuen Zyklus.
    """

    AccountRetentionNotice.objects.filter(
        user_id=user.pk,
    ).delete()
