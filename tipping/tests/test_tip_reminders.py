from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import (
    TestCase,
    override_settings,
)
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    Match,
    Prediction,
    TipReminderDelivery,
    Tournament,
    UserProfile,
)
from tipping.tip_reminders import (
    send_due_tip_reminders,
)


class TipReminderSettingsViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="reminder-settings-user",
            email="settings@example.com",
            password="safe-test-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Settings-Turnier",
        )
        self.group = Group.objects.create(
            name="Settings-Gruppe",
            tournament=self.tournament,
            owner=self.user,
        )
        GroupMembership.objects.create(
            user=self.user,
            group=self.group,
            is_creator=True,
        )

    def test_settings_require_login(self):
        response = self.client.get(
            reverse("notification_settings")
        )

        self.assertEqual(
            response.status_code,
            302,
        )
        self.assertIn(
            reverse("account_login"),
            response.url,
        )

    def test_get_creates_disabled_profile(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("notification_settings")
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        profile = UserProfile.objects.get(
            user=self.user
        )
        self.assertFalse(
            profile.tip_reminders_enabled
        )
        self.assertContains(
            response,
            "Activar recordatorios por correo",
        )

    def test_user_can_enable_and_disable_reminders(self):
        self.client.force_login(self.user)
        url = reverse("notification_settings")

        response = self.client.post(
            url,
            {
                "tip_reminders_enabled": "on",
            },
        )

        self.assertRedirects(response, url)
        profile = UserProfile.objects.get(
            user=self.user
        )
        self.assertTrue(
            profile.tip_reminders_enabled
        )

        self.client.post(url, {})
        profile.refresh_from_db()
        self.assertFalse(
            profile.tip_reminders_enabled
        )

    def test_profile_menu_links_to_settings(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("notification_settings")
        )

        self.assertContains(
            response,
            f'href="{reverse("notification_settings")}"',
        )

    def test_email_tip_link_activates_members_group(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                "group_tip_redirect",
                args=[
                    self.group.id,
                ],
            ),
            {
                "md": "3",
            },
        )

        self.assertRedirects(
            response,
            f'{reverse("tippen")}?md=3',
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.session[
                "active_group_id"
            ],
            self.group.id,
        )

    def test_email_tip_link_rejects_non_member(self):
        outsider = (
            get_user_model().objects.create_user(
                username="reminder-outsider",
                password="safe-test-password-123",
            )
        )
        self.client.force_login(outsider)

        response = self.client.get(
            reverse(
                "group_tip_redirect",
                args=[
                    self.group.id,
                ],
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )


@override_settings(
    EMAIL_BACKEND=(
        "django.core.mail.backends.locmem."
        "EmailBackend"
    ),
    PUBLIC_BASE_URL="https://puntero.example",
    TIP_REMINDERS_ENABLED=True,
    TIP_REMINDER_LEAD_HOURS=24,
)
class TipReminderServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.now = timezone.now()
        self.user = User.objects.create_user(
            username="reminder-user",
            email="verified@example.com",
            password="safe-test-password-123",
        )
        EmailAddress.objects.create(
            user=self.user,
            email="verified@example.com",
            verified=True,
            primary=True,
        )
        UserProfile.objects.create(
            user=self.user,
            tip_reminders_enabled=True,
        )
        self.tournament = Tournament.objects.create(
            name="Reminder-Turnier",
        )
        self.group = Group.objects.create(
            name="Amigos Quito",
            tournament=self.tournament,
            owner=self.user,
        )
        GroupMembership.objects.create(
            user=self.user,
            group=self.group,
            is_creator=True,
        )
        self.match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                self.now
                + timedelta(hours=12)
            ),
            matchday=3,
        )

    def test_sends_and_records_one_reminder(self):
        result = send_due_tip_reminders(
            now=self.now
        )

        self.assertEqual(result.recipients, 1)
        self.assertEqual(
            result.deliveries_created,
            1,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            [
                "verified@example.com",
            ],
        )
        self.assertIn(
            "Equipo A",
            mail.outbox[0].body,
        )
        self.assertIn(
            (
                "https://puntero.example"
                f"/groups/{self.group.id}/"
                "pronosticar/?md=3"
            ),
            mail.outbox[0].body,
        )
        self.assertTrue(
            TipReminderDelivery.objects.filter(
                user=self.user,
                group=self.group,
                match=self.match,
            ).exists()
        )

    def test_second_run_does_not_send_duplicate(self):
        send_due_tip_reminders(now=self.now)
        second_result = send_due_tip_reminders(
            now=self.now
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            second_result.due_deliveries,
            0,
        )
        self.assertEqual(
            TipReminderDelivery.objects.count(),
            1,
        )

    def test_complete_prediction_is_not_reminded(self):
        Prediction.objects.create(
            user=self.user,
            group=self.group,
            match=self.match,
            pred_home=2,
            pred_away=1,
        )

        result = send_due_tip_reminders(
            now=self.now
        )

        self.assertEqual(result.due_deliveries, 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            TipReminderDelivery.objects.exists()
        )

    def test_unverified_address_is_not_used(self):
        EmailAddress.objects.update(
            verified=False
        )

        result = send_due_tip_reminders(
            now=self.now
        )

        self.assertEqual(result.recipients, 0)
        self.assertEqual(
            result.users_without_verified_email,
            1,
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_opted_out_user_is_not_reminded(self):
        UserProfile.objects.filter(
            user=self.user
        ).update(
            tip_reminders_enabled=False
        )

        result = send_due_tip_reminders(
            now=self.now
        )

        self.assertEqual(result.due_deliveries, 0)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        TIP_REMINDERS_ENABLED=False,
    )
    def test_global_switch_prevents_actual_send(self):
        result = send_due_tip_reminders(
            now=self.now
        )

        self.assertFalse(result.enabled)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            TipReminderDelivery.objects.exists()
        )

    @override_settings(
        TIP_REMINDERS_ENABLED=False,
    )
    def test_dry_run_never_sends_or_records(self):
        result = send_due_tip_reminders(
            now=self.now,
            dry_run=True,
        )

        self.assertTrue(result.dry_run)
        self.assertEqual(result.recipients, 1)
        self.assertEqual(result.due_deliveries, 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            TipReminderDelivery.objects.exists()
        )

    def test_multiple_matches_are_bundled(self):
        second_match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=(
                self.now
                + timedelta(hours=18)
            ),
            matchday=3,
        )

        result = send_due_tip_reminders(
            now=self.now
        )

        self.assertEqual(result.recipients, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            TipReminderDelivery.objects.count(),
            2,
        )
        self.assertTrue(
            TipReminderDelivery.objects.filter(
                match=second_match
            ).exists()
        )
        self.assertIn(
            "Equipo C",
            mail.outbox[0].body,
        )

    def test_failure_is_not_recorded_and_can_retry(self):
        with self.assertLogs(
            "tipping.tip_reminders",
            level="ERROR",
        ):
            with patch(
                (
                    "tipping.tip_reminders."
                    "_send_user_reminder"
                ),
                side_effect=RuntimeError(
                    "SMTP unavailable"
                ),
            ):
                result = send_due_tip_reminders(
                    now=self.now
                )

        self.assertEqual(result.failures, 1)
        self.assertFalse(
            TipReminderDelivery.objects.exists()
        )

        retry_result = send_due_tip_reminders(
            now=self.now
        )
        self.assertEqual(retry_result.recipients, 1)
        self.assertEqual(
            TipReminderDelivery.objects.count(),
            1,
        )

    def test_management_command_supports_dry_run(self):
        output = StringIO()

        call_command(
            "send_tip_reminders",
            dry_run=True,
            stdout=output,
        )

        self.assertIn(
            "Testlauf beendet",
            output.getvalue(),
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            TipReminderDelivery.objects.exists()
        )
