from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
    UserProfile,
)


User = get_user_model()


@override_settings(
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
    EMAIL_BACKEND=(
        "django.core.mail.backends.locmem.EmailBackend"
    ),
    LEGAL_PAGES_ENABLED=False,
    TIP_REMINDERS_ENABLED=False,
    ACCOUNT_RETENTION_NOTICES_ENABLED=False,
)
class ReleaseAcceptanceTests(TestCase):
    """Ein zusammenhängender Smoke-Test der wichtigsten Nutzerwege."""

    owner_password = "Safe-acceptance-password-2026"
    member_password = "Safe-member-password-2026"

    def log_in(self, identifier, password):
        response = self.client.post(
            reverse("account_login"),
            {
                "login": identifier,
                "password": password,
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_complete_manual_result_workflow(self):
        health_response = self.client.get(
            reverse("health_check")
        )
        self.assertEqual(
            health_response.status_code,
            200,
        )

        self.assertEqual(
            self.client.get(
                reverse("privacy_policy")
            ).status_code,
            404,
        )

        signup_response = self.client.get(
            reverse("account_signup")
        )
        self.assertContains(
            signup_response,
            "Confirmo que tengo al menos 18 años.",
        )

        mail.outbox.clear()
        signup_response = self.client.post(
            reverse("account_signup"),
            {
                "username": "acceptance-owner",
                "email": "owner@acceptance.invalid",
                "password1": self.owner_password,
                "password2": self.owner_password,
                "is_adult": "on",
            },
        )

        self.assertEqual(
            signup_response.status_code,
            302,
        )
        self.assertEqual(
            len(mail.outbox),
            1,
        )

        owner = User.objects.get(
            username="acceptance-owner"
        )
        owner_address = EmailAddress.objects.get(
            user=owner,
            email="owner@acceptance.invalid",
        )
        self.assertFalse(owner_address.verified)

        owner_address.verified = True
        owner_address.save(
            update_fields=["verified"]
        )

        self.client.logout()
        self.log_in(
            "owner@acceptance.invalid",
            self.owner_password,
        )
        self.assertEqual(
            self.client.session.get("_auth_user_id"),
            str(owner.pk),
        )

        tournament = Tournament.objects.create(
            name="Liga de aceptación",
            season_start=(
                timezone.now()
                + timedelta(days=30)
            ),
        )

        with self.captureOnCommitCallbacks(
            execute=True
        ):
            create_response = self.client.post(
                reverse("create_group"),
                {
                    "name": "Grupo de aceptación",
                    "tournament": tournament.pk,
                },
            )

        self.assertEqual(
            create_response.status_code,
            302,
        )

        group = Group.objects.get(
            name="Grupo de aceptación"
        )
        self.assertEqual(group.owner, owner)
        self.assertTrue(
            GroupMembership.objects.filter(
                group=group,
                user=owner,
                is_creator=True,
            ).exists()
        )

        match = Match.objects.create(
            tournament=tournament,
            home_team="Equipo Azul",
            away_team="Equipo Blanco",
            kickoff=(
                timezone.now()
                + timedelta(days=1)
            ),
            matchday=1,
        )

        owner_tip_response = self.client.post(
            f"{reverse('tippen')}?md=1",
            {
                f"pred_home_{match.pk}": "2",
                f"pred_away_{match.pk}": "1",
            },
        )
        self.assertEqual(
            owner_tip_response.status_code,
            302,
        )

        member = User.objects.create_user(
            username="acceptance-member",
            email="member@acceptance.invalid",
            password=self.member_password,
        )
        EmailAddress.objects.create(
            user=member,
            email=member.email,
            verified=True,
            primary=True,
        )

        self.client.logout()
        self.log_in(
            "acceptance-member",
            self.member_password,
        )

        with self.captureOnCommitCallbacks(
            execute=True
        ):
            join_response = self.client.post(
                reverse("join_group"),
                {"code": group.join_code.lower()},
            )

        self.assertEqual(
            join_response.status_code,
            302,
        )
        self.assertTrue(
            GroupMembership.objects.filter(
                group=group,
                user=member,
            ).exists()
        )
        self.assertEqual(
            self.client.session.get(
                "active_group_id"
            ),
            group.pk,
        )

        member_tip_response = self.client.post(
            f"{reverse('tippen')}?md=1",
            {
                f"pred_home_{match.pk}": "1",
                f"pred_away_{match.pk}": "0",
            },
        )
        self.assertEqual(
            member_tip_response.status_code,
            302,
        )

        match.home_score = 2
        match.away_score = 1

        with self.captureOnCommitCallbacks(
            execute=True
        ):
            match.save(
                update_fields=[
                    "home_score",
                    "away_score",
                ]
            )

        owner_prediction = Prediction.objects.get(
            group=group,
            user=owner,
            match=match,
        )
        member_prediction = Prediction.objects.get(
            group=group,
            user=member,
            match=match,
        )
        self.assertEqual(owner_prediction.points, 4)
        self.assertEqual(member_prediction.points, 3)

        standings = list(
            GroupStanding.objects
            .filter(group=group)
            .order_by("-match_points")
            .values_list(
                "user__username",
                "match_points",
                "matchday_wins",
            )
        )
        self.assertEqual(
            standings,
            [
                ("acceptance-owner", 4, 1),
                ("acceptance-member", 3, 0),
            ],
        )

        scores = dict(
            MatchdayScore.objects
            .filter(
                group=group,
                matchday=1,
            )
            .values_list(
                "user__username",
                "rank",
            )
        )
        self.assertEqual(
            scores,
            {
                "acceptance-owner": 1,
                "acceptance-member": 2,
            },
        )

        matchday_response = self.client.get(
            reverse("spieltag"),
            {"md": 1},
        )
        self.assertContains(
            matchday_response,
            "Vista por fecha – Fecha 1",
        )
        self.assertContains(
            matchday_response,
            "acceptance-owner",
        )
        self.assertContains(
            matchday_response,
            "acceptance-member",
        )

        table_response = self.client.get(
            reverse("tabelle")
        )
        self.assertContains(
            table_response,
            "Tabla general",
        )
        self.assertContains(
            table_response,
            "acceptance-owner",
        )
        self.assertContains(
            table_response,
            "acceptance-member",
        )

        reminder_response = self.client.post(
            reverse("notification_settings"),
            {"tip_reminders_enabled": "on"},
        )
        self.assertEqual(
            reminder_response.status_code,
            302,
        )
        self.assertTrue(
            UserProfile.objects.get(
                user=member
            ).tip_reminders_enabled
        )
