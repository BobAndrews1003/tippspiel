from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import (
    TestCase,
    override_settings,
)
from django.utils import timezone

from tipping.account_retention_notices import (
    send_due_account_retention_notices,
)
from tipping.models import (
    AccountRetentionNotice,
    Group,
    Tournament,
)


@override_settings(
    EMAIL_BACKEND=(
        "django.core.mail.backends.locmem."
        "EmailBackend"
    ),
    PUBLIC_BASE_URL="https://puntero.example",
    ACCOUNT_RETENTION_NOTICES_ENABLED=True,
    DATA_RETENTION_INACTIVE_ACCOUNT_DAYS=730,
    ACCOUNT_RETENTION_FIRST_NOTICE_DAYS=30,
    ACCOUNT_RETENTION_FINAL_NOTICE_DAYS=7,
    ACCOUNT_RETENTION_NOTICE_BATCH_SIZE=100,
    ACCOUNT_RETENTION_NOTICE_CLAIM_STALE_MINUTES=60,
)
class AccountRetentionNoticeTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.now = timezone.now()

    def create_old_user(
        self,
        username,
        *,
        days_inactive,
        verified=True,
        is_staff=False,
    ):
        user = self.user_model.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="safe-test-password-123",
            is_staff=is_staff,
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=verified,
        )
        self.user_model.objects.filter(
            pk=user.pk,
        ).update(
            date_joined=(
                self.now
                - timedelta(days=days_inactive)
            ),
            last_login=None,
        )
        user.refresh_from_db()

        return user

    def test_first_warning_is_sent_and_not_duplicated(self):
        user = self.create_old_user(
            "first-warning",
            days_inactive=701,
        )

        first_result = send_due_account_retention_notices(
            now=self.now,
            dry_run=False,
        )

        self.assertEqual(first_result.first_due, 1)
        self.assertEqual(first_result.final_due, 0)
        self.assertEqual(first_result.sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            "Aviso: tu cuenta de Puntero está inactiva",
            mail.outbox[0].subject,
        )
        self.assertIn(
            "https://puntero.example/accounts/login/",
            mail.outbox[0].body,
        )

        notice = AccountRetentionNotice.objects.get(
            user=user,
        )
        self.assertIsNotNone(
            notice.first_warning_sent_at
        )
        self.assertIsNone(
            notice.final_warning_sent_at
        )

        second_result = send_due_account_retention_notices(
            now=self.now,
            dry_run=False,
        )

        self.assertEqual(second_result.first_due, 0)
        self.assertEqual(second_result.final_due, 0)
        self.assertEqual(second_result.sent, 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_final_warning_requires_first_warning_interval(self):
        user = self.create_old_user(
            "final-warning",
            days_inactive=725,
        )
        notice = AccountRetentionNotice.objects.create(
            user=user,
            inactivity_since=user.date_joined,
            first_warning_sent_at=(
                self.now - timedelta(days=24)
            ),
        )

        result = send_due_account_retention_notices(
            now=self.now,
            dry_run=False,
        )

        self.assertEqual(result.first_due, 0)
        self.assertEqual(result.final_due, 1)
        self.assertEqual(result.sent, 1)
        self.assertIn(
            "Último aviso",
            mail.outbox[0].subject,
        )
        notice.refresh_from_db()
        self.assertIsNotNone(
            notice.final_warning_sent_at
        )

    def test_late_first_warning_still_grants_thirty_days(self):
        user = self.create_old_user(
            "late-warning",
            days_inactive=800,
        )

        result = send_due_account_retention_notices(
            now=self.now,
            dry_run=False,
        )

        self.assertEqual(result.first_due, 1)
        self.assertEqual(result.final_due, 0)
        expected_date = timezone.localtime(
            self.now + timedelta(days=30)
        ).strftime("%d/%m/%Y")
        self.assertIn(
            expected_date,
            mail.outbox[0].body,
        )
        notice = AccountRetentionNotice.objects.get(
            user=user,
        )
        self.assertIsNone(
            notice.final_warning_sent_at
        )

    def test_successful_login_clears_warning_cycle(self):
        user = self.create_old_user(
            "returning-user",
            days_inactive=701,
        )
        AccountRetentionNotice.objects.create(
            user=user,
            inactivity_since=user.date_joined,
            first_warning_sent_at=self.now,
        )

        logged_in = self.client.login(
            username=user.username,
            password="safe-test-password-123",
        )

        self.assertTrue(logged_in)
        self.assertFalse(
            AccountRetentionNotice.objects.filter(
                user=user,
            ).exists()
        )
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)

        result = send_due_account_retention_notices(
            now=self.now + timedelta(minutes=1),
            dry_run=False,
        )
        self.assertEqual(result.first_due, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_group_owner_receives_protection_explanation(self):
        user = self.create_old_user(
            "group-owner-warning",
            days_inactive=701,
        )
        tournament = Tournament.objects.create(
            name="Warnungs-Turnier",
        )
        Group.objects.create(
            tournament=tournament,
            name="Warnungs-Gruppe",
            owner=user,
        )

        send_due_account_retention_notices(
            now=self.now,
            dry_run=False,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            "administras uno o más grupos",
            mail.outbox[0].body,
        )
        self.assertIn(
            "permanece protegida",
            mail.outbox[0].body,
        )

    def test_unverified_and_staff_accounts_are_excluded(self):
        self.create_old_user(
            "unverified-warning",
            days_inactive=701,
            verified=False,
        )
        self.create_old_user(
            "staff-warning",
            days_inactive=701,
            is_staff=True,
        )

        result = send_due_account_retention_notices(
            now=self.now,
            dry_run=False,
        )

        self.assertEqual(result.first_due, 0)
        self.assertEqual(result.sent, 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            AccountRetentionNotice.objects.exists()
        )

    def test_failed_send_releases_claim_for_retry(self):
        user = self.create_old_user(
            "retry-warning",
            days_inactive=701,
        )

        with self.assertLogs(
            "tipping.account_retention_notices",
            level="ERROR",
        ):
            with patch(
                (
                    "tipping.account_retention_notices."
                    "_send_account_retention_notice"
                ),
                side_effect=RuntimeError(
                    "SMTP unavailable"
                ),
            ):
                failed_result = (
                    send_due_account_retention_notices(
                        now=self.now,
                        dry_run=False,
                    )
                )

        self.assertEqual(failed_result.failures, 1)
        notice = AccountRetentionNotice.objects.get(
            user=user,
        )
        self.assertIsNone(
            notice.first_warning_claimed_at
        )
        self.assertIsNone(
            notice.first_warning_sent_at
        )

        retry_result = send_due_account_retention_notices(
            now=self.now + timedelta(minutes=1),
            dry_run=False,
        )

        self.assertEqual(retry_result.sent, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_default_command_is_a_dry_run(self):
        self.create_old_user(
            "command-dry-run",
            days_inactive=701,
        )
        output = StringIO()

        call_command(
            "send_account_retention_notices",
            stdout=output,
        )

        self.assertIn(
            "Prüfmodus beendet: 1 erste Warnungen",
            output.getvalue(),
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            AccountRetentionNotice.objects.exists()
        )

    @override_settings(
        ACCOUNT_RETENTION_NOTICES_ENABLED=False,
    )
    def test_global_switch_blocks_execute(self):
        self.create_old_user(
            "disabled-warning",
            days_inactive=701,
        )
        output = StringIO()

        call_command(
            "send_account_retention_notices",
            execute=True,
            stdout=output,
        )

        self.assertIn(
            "global deaktiviert",
            output.getvalue(),
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            AccountRetentionNotice.objects.exists()
        )

    def test_command_rejects_invalid_limit(self):
        with self.assertRaises(CommandError):
            call_command(
                "send_account_retention_notices",
                limit=0,
                stdout=StringIO(),
            )
