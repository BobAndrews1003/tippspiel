from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from allauth.account.models import (
    EmailAddress,
    EmailConfirmation,
)
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Exists, F, OuterRef
from django.db.models.functions import Coalesce
from django.utils import timezone

from .membership_processing import (
    rebuild_group_after_membership_change,
)
from .models import (
    BonusPrediction,
    Group,
    GroupMembership,
    GroupStanding,
    MatchdayScore,
    Prediction,
    TipReminderDelivery,
)
from .signal_control import (
    suppress_read_model_delete_signals,
)


@dataclass(frozen=True)
class RetentionSnapshot:
    expired_sessions: int
    expired_email_confirmations: int
    old_reminder_deliveries: int
    old_inactive_memberships: int
    old_unverified_accounts: int
    protected_unverified_accounts: int
    inactive_accounts_for_notice: int
    inactive_group_owners_for_notice: int


@dataclass(frozen=True)
class RetentionExecution:
    expired_sessions: int
    expired_email_confirmations: int
    old_reminder_deliveries: int
    old_inactive_memberships: int
    old_unverified_accounts: int
    rebuilt_groups: int


class PersonalDataRetention:
    """
    Ermittelt und bereinigt personenbezogene Altdaten.

    Bestätigte inaktive Konten werden bewusst nur gemeldet. Ihre
    Löschung darf erst aktiviert werden, wenn die vorgesehenen
    Warnungen 30 und 7 Tage vor dem Löschtermin umgesetzt sind.
    """

    def __init__(
        self,
        *,
        limit: int = 500,
        now=None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit muss mindestens 1 sein.")

        self.limit = limit
        self.now = now or timezone.now()
        self.user_model = get_user_model()

    def _cutoff(self, setting_name: str):
        return self.now - timedelta(
            days=getattr(settings, setting_name),
        )

    def _users_with_retention_state(self):
        email_addresses = EmailAddress.objects.filter(
            user_id=OuterRef("pk"),
        )

        return self.user_model.objects.annotate(
            retention_last_activity=Coalesce(
                "last_login",
                "date_joined",
            ),
            retention_has_email=Exists(
                email_addresses,
            ),
            retention_has_verified_email=Exists(
                email_addresses.filter(
                    verified=True,
                )
            ),
            retention_has_membership=Exists(
                GroupMembership.all_objects.filter(
                    user_id=OuterRef("pk"),
                )
            ),
            retention_owns_group=Exists(
                Group.objects.filter(
                    owner_id=OuterRef("pk"),
                )
            ),
            retention_has_prediction=Exists(
                Prediction.objects.filter(
                    user_id=OuterRef("pk"),
                )
            ),
            retention_has_bonus_prediction=Exists(
                BonusPrediction.objects.filter(
                    user_id=OuterRef("pk"),
                )
            ),
            retention_has_matchday_score=Exists(
                MatchdayScore.objects.filter(
                    user_id=OuterRef("pk"),
                )
            ),
            retention_has_standing=Exists(
                GroupStanding.objects.filter(
                    user_id=OuterRef("pk"),
                )
            ),
            retention_has_reminder=Exists(
                TipReminderDelivery.objects.filter(
                    user_id=OuterRef("pk"),
                )
            ),
        )

    def _old_unverified_accounts(self):
        return self._users_with_retention_state().filter(
            retention_last_activity__lt=self._cutoff(
                "DATA_RETENTION_UNVERIFIED_ACCOUNT_DAYS"
            ),
            retention_has_verified_email=False,
        )

    def _deletable_unverified_accounts(self):
        return self._old_unverified_accounts().filter(
            is_staff=False,
            is_superuser=False,
            retention_has_email=True,
            retention_has_membership=False,
            retention_owns_group=False,
            retention_has_prediction=False,
            retention_has_bonus_prediction=False,
            retention_has_matchday_score=False,
            retention_has_standing=False,
            retention_has_reminder=False,
        )

    def _inactive_accounts_for_notice(self):
        return self._users_with_retention_state().filter(
            is_staff=False,
            is_superuser=False,
            retention_last_activity__lt=self._cutoff(
                "DATA_RETENTION_INACTIVE_ACCOUNT_DAYS"
            ),
            retention_has_verified_email=True,
        )

    def _old_inactive_memberships(self):
        return (
            GroupMembership.all_objects
            .filter(
                is_active=False,
                is_creator=False,
                removed_at__lt=self._cutoff(
                    "DATA_RETENTION_INACTIVE_MEMBERSHIP_DAYS"
                ),
            )
            .exclude(
                group__owner_id=F("user_id"),
            )
        )

    def _expired_email_confirmations(self):
        return EmailConfirmation.objects.filter(
            created__lt=(
                self.now
                - timedelta(
                    days=(
                        settings
                        .ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS
                    ),
                )
            ),
        )

    def _old_reminder_deliveries(self):
        return TipReminderDelivery.objects.filter(
            sent_at__lt=self._cutoff(
                "DATA_RETENTION_REMINDER_DELIVERY_DAYS"
            ),
        )

    def snapshot(self) -> RetentionSnapshot:
        old_unverified_accounts = (
            self._old_unverified_accounts()
        )
        deletable_unverified_accounts = (
            self._deletable_unverified_accounts()
        )
        inactive_accounts = (
            self._inactive_accounts_for_notice()
        )

        old_unverified_count = (
            old_unverified_accounts.count()
        )
        deletable_unverified_count = (
            deletable_unverified_accounts.count()
        )

        return RetentionSnapshot(
            expired_sessions=(
                Session.objects
                .filter(expire_date__lt=self.now)
                .count()
            ),
            expired_email_confirmations=(
                self._expired_email_confirmations().count()
            ),
            old_reminder_deliveries=(
                self._old_reminder_deliveries().count()
            ),
            old_inactive_memberships=(
                self._old_inactive_memberships().count()
            ),
            old_unverified_accounts=(
                deletable_unverified_count
            ),
            protected_unverified_accounts=(
                old_unverified_count
                - deletable_unverified_count
            ),
            inactive_accounts_for_notice=(
                inactive_accounts.count()
            ),
            inactive_group_owners_for_notice=(
                inactive_accounts
                .filter(retention_owns_group=True)
                .count()
            ),
        )

    def _limited_ids(self, queryset) -> list:
        return list(
            queryset
            .order_by("pk")
            .values_list("pk", flat=True)[: self.limit]
        )

    def execute(self) -> RetentionExecution:
        with transaction.atomic():
            session_ids = self._limited_ids(
                Session.objects.filter(
                    expire_date__lt=self.now,
                )
            )
            confirmation_ids = self._limited_ids(
                self._expired_email_confirmations()
            )
            reminder_ids = self._limited_ids(
                self._old_reminder_deliveries()
            )

            # Mitgliedschaft und Gruppe werden gesperrt. So kann eine
            # parallele Reaktivierung oder Eigentumsübertragung nicht
            # zwischen Auswahl und Löschung geraten.
            initial_membership_rows = list(
                self._old_inactive_memberships()
                .select_for_update()
                .order_by("pk")
                .values_list(
                    "pk",
                    "group_id",
                    "user_id",
                )[: self.limit]
            )
            initial_membership_ids = [
                membership_id
                for membership_id, _, _ in (
                    initial_membership_rows
                )
            ]
            initial_group_ids = {
                group_id
                for _, group_id, _ in initial_membership_rows
            }
            list(
                Group.objects
                .select_for_update()
                .filter(pk__in=initial_group_ids)
                .values_list("pk", flat=True)
            )
            membership_rows = list(
                self._old_inactive_memberships()
                .filter(pk__in=initial_membership_ids)
                .order_by("pk")
                .values_list(
                    "pk",
                    "group_id",
                    "user_id",
                )
            )
            group_ids = {
                group_id
                for _, group_id, _ in membership_rows
            }

            # Nutzer- und E-Mail-Zeilen werden ebenfalls gesperrt und
            # danach erneut geprüft. Eine gleichzeitig bestätigte
            # Registrierung wird dadurch nicht versehentlich gelöscht.
            initial_user_ids = list(
                self._deletable_unverified_accounts()
                .select_for_update()
                .order_by("pk")
                .values_list("pk", flat=True)[: self.limit]
            )
            list(
                EmailAddress.objects
                .select_for_update()
                .filter(user_id__in=initial_user_ids)
                .values_list("pk", flat=True)
            )
            user_ids = list(
                self._deletable_unverified_accounts()
                .filter(pk__in=initial_user_ids)
                .order_by("pk")
                .values_list("pk", flat=True)
            )

            Session.objects.filter(
                pk__in=session_ids,
            ).delete()
            EmailConfirmation.objects.filter(
                pk__in=confirmation_ids,
            ).delete()
            TipReminderDelivery.objects.filter(
                pk__in=reminder_ids,
            ).delete()

            with suppress_read_model_delete_signals():
                for membership_id, group_id, user_id in (
                    membership_rows
                ):
                    Prediction.objects.filter(
                        group_id=group_id,
                        user_id=user_id,
                    ).delete()
                    BonusPrediction.objects.filter(
                        group_id=group_id,
                        user_id=user_id,
                    ).delete()
                    MatchdayScore.objects.filter(
                        group_id=group_id,
                        user_id=user_id,
                    ).delete()
                    GroupStanding.objects.filter(
                        group_id=group_id,
                        user_id=user_id,
                    ).delete()
                    TipReminderDelivery.objects.filter(
                        group_id=group_id,
                        user_id=user_id,
                    ).delete()
                    GroupMembership.all_objects.filter(
                        pk=membership_id,
                    ).delete()

            for group_id in sorted(group_ids):
                rebuild_group_after_membership_change(
                    group_id=group_id,
                )

            self.user_model.objects.filter(
                pk__in=user_ids,
            ).delete()

        return RetentionExecution(
            expired_sessions=len(session_ids),
            expired_email_confirmations=(
                len(confirmation_ids)
            ),
            old_reminder_deliveries=len(reminder_ids),
            old_inactive_memberships=len(membership_rows),
            old_unverified_accounts=len(user_ids),
            rebuilt_groups=len(group_ids),
        )
