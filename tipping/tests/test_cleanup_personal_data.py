from datetime import timedelta
from io import StringIO

from allauth.account.models import (
    EmailAddress,
    EmailConfirmation,
)
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from tipping.models import (
    BonusPrediction,
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
    TipReminderDelivery,
    Tournament,
)


class CleanupPersonalDataTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.now = timezone.now()

    def create_user_with_email(
        self,
        username,
        *,
        verified,
        days_old=0,
    ):
        user = self.user_model.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="safe-test-password-123",
        )
        email_address = EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=verified,
        )

        if days_old:
            self.user_model.objects.filter(
                pk=user.pk,
            ).update(
                date_joined=(
                    self.now
                    - timedelta(days=days_old)
                ),
                last_login=None,
            )
            user.refresh_from_db()

        return user, email_address

    def create_session(self, key, *, days_from_now):
        return Session.objects.create(
            session_key=key,
            session_data="e30:1test:test",
            expire_date=(
                self.now
                + timedelta(days=days_from_now)
            ),
        )

    def test_default_mode_only_reports_candidates(self):
        stale_user, _ = self.create_user_with_email(
            "dry-run-unverified",
            verified=False,
            days_old=20,
        )
        expired_session = self.create_session(
            "expired-dry-run",
            days_from_now=-1,
        )
        output = StringIO()

        call_command(
            "cleanup_personal_data",
            stdout=output,
        )

        self.assertTrue(
            self.user_model.objects.filter(
                pk=stale_user.pk,
            ).exists()
        )
        self.assertTrue(
            Session.objects.filter(
                pk=expired_session.pk,
            ).exists()
        )
        self.assertIn(
            "Prüfmodus: Es wurden keine Daten gelöscht.",
            output.getvalue(),
        )

    def test_execute_applies_safe_retention_categories(self):
        expired_session = self.create_session(
            "expired-execute",
            days_from_now=-1,
        )
        current_session = self.create_session(
            "current-execute",
            days_from_now=1,
        )

        confirmation_user, confirmation_email = (
            self.create_user_with_email(
                "confirmation-user",
                verified=False,
            )
        )
        expired_confirmation = (
            EmailConfirmation.objects.create(
                email_address=confirmation_email,
                key="expired-confirmation",
            )
        )
        EmailConfirmation.objects.filter(
            pk=expired_confirmation.pk,
        ).update(
            created=self.now - timedelta(days=4),
        )
        current_confirmation = (
            EmailConfirmation.objects.create(
                email_address=confirmation_email,
                key="current-confirmation",
            )
        )

        stale_unverified, _ = self.create_user_with_email(
            "stale-unverified",
            verified=False,
            days_old=20,
        )
        recent_unverified, _ = self.create_user_with_email(
            "recent-unverified",
            verified=False,
            days_old=5,
        )
        inactive_verified, _ = self.create_user_with_email(
            "inactive-verified",
            verified=True,
            days_old=800,
        )

        tournament = Tournament.objects.create(
            name="Retention-Turnier",
        )
        owner, _ = self.create_user_with_email(
            "retention-owner",
            verified=True,
        )
        group = Group.objects.create(
            tournament=tournament,
            name="Retention-Gruppe",
            owner=owner,
        )
        GroupMembership.objects.create(
            user=owner,
            group=group,
            is_creator=True,
        )

        protected_owner, _ = self.create_user_with_email(
            "protected-unverified-owner",
            verified=False,
            days_old=20,
        )
        protected_group = Group.objects.create(
            tournament=tournament,
            name="Geschützte Gruppe",
            owner=protected_owner,
        )

        former_member, _ = self.create_user_with_email(
            "former-member",
            verified=True,
        )
        membership = GroupMembership.objects.create(
            user=former_member,
            group=group,
        )
        match = Match.objects.create(
            tournament=tournament,
            home_team="Local",
            away_team="Visitante",
            kickoff=self.now + timedelta(days=10),
            matchday=1,
        )
        other_match = Match.objects.create(
            tournament=tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=self.now + timedelta(days=11),
            matchday=1,
        )
        recent_match = Match.objects.create(
            tournament=tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=self.now + timedelta(days=12),
            matchday=1,
        )
        prediction = Prediction.objects.create(
            user=former_member,
            group=group,
            match=match,
            pred_home=1,
            pred_away=0,
        )
        bonus_prediction = BonusPrediction.objects.create(
            user=former_member,
            group=group,
            bonus_type="meister",
            value="Local",
        )
        matchday_score = MatchdayScore.objects.create(
            user=former_member,
            group=group,
            matchday=1,
        )
        standing = GroupStanding.objects.create(
            user=former_member,
            group=group,
        )
        member_reminder = TipReminderDelivery.objects.create(
            user=former_member,
            group=group,
            match=match,
        )
        old_reminder = TipReminderDelivery.objects.create(
            user=owner,
            group=group,
            match=other_match,
        )
        TipReminderDelivery.objects.filter(
            pk=old_reminder.pk,
        ).update(
            sent_at=self.now - timedelta(days=100),
        )
        recent_reminder = TipReminderDelivery.objects.create(
            user=owner,
            group=group,
            match=recent_match,
        )

        GroupMembership.all_objects.filter(
            pk=membership.pk,
        ).update(
            is_active=False,
            removed_at=self.now - timedelta(days=400),
        )

        output = StringIO()
        call_command(
            "cleanup_personal_data",
            execute=True,
            stdout=output,
        )

        self.assertFalse(
            Session.objects.filter(
                pk=expired_session.pk,
            ).exists()
        )
        self.assertTrue(
            Session.objects.filter(
                pk=current_session.pk,
            ).exists()
        )
        self.assertFalse(
            EmailConfirmation.objects.filter(
                pk=expired_confirmation.pk,
            ).exists()
        )
        self.assertTrue(
            EmailConfirmation.objects.filter(
                pk=current_confirmation.pk,
            ).exists()
        )
        self.assertFalse(
            self.user_model.objects.filter(
                pk=stale_unverified.pk,
            ).exists()
        )
        self.assertTrue(
            self.user_model.objects.filter(
                pk=recent_unverified.pk,
            ).exists()
        )
        self.assertTrue(
            self.user_model.objects.filter(
                pk=inactive_verified.pk,
            ).exists()
        )
        self.assertTrue(
            self.user_model.objects.filter(
                pk=protected_owner.pk,
            ).exists()
        )
        self.assertTrue(
            Group.objects.filter(
                pk=protected_group.pk,
            ).exists()
        )
        self.assertFalse(
            GroupMembership.all_objects.filter(
                pk=membership.pk,
            ).exists()
        )

        for model, instance in (
            (Prediction, prediction),
            (BonusPrediction, bonus_prediction),
            (MatchdayScore, matchday_score),
            (GroupStanding, standing),
            (TipReminderDelivery, member_reminder),
            (TipReminderDelivery, old_reminder),
        ):
            self.assertFalse(
                model.objects.filter(
                    pk=instance.pk,
                ).exists()
            )

        self.assertTrue(
            TipReminderDelivery.objects.filter(
                pk=recent_reminder.pk,
            ).exists()
        )
        self.assertIn(
            "Bestätigte inaktive Konten wurden nicht gelöscht",
            output.getvalue(),
        )

    def test_execute_respects_limit_per_category(self):
        stale_users = [
            self.create_user_with_email(
                f"limited-user-{index}",
                verified=False,
                days_old=20,
            )[0]
            for index in range(2)
        ]

        call_command(
            "cleanup_personal_data",
            execute=True,
            limit=1,
            stdout=StringIO(),
        )

        remaining_count = (
            self.user_model.objects
            .filter(
                pk__in=[user.pk for user in stale_users],
            )
            .count()
        )
        self.assertEqual(remaining_count, 1)

    def test_rejects_invalid_limit(self):
        with self.assertRaises(CommandError):
            call_command(
                "cleanup_personal_data",
                limit=0,
                stdout=StringIO(),
            )
