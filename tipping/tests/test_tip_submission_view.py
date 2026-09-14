from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    Match,
    Prediction,
    Tournament,
)


class TipSubmissionViewTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="tip-submission-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Tip-Submission-Turnier",
        )

        self.group = Group.objects.create(
            name="Tip-Submission-Gruppe",
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
                timezone.now()
                + timedelta(days=1)
            ),
            matchday=1,
        )

        self.client.force_login(self.user)

        session = self.client.session
        session["active_group_id"] = self.group.id
        session.save()

    def test_valid_prediction_is_saved_via_post(self):
        response = self.client.post(
            f"{reverse('tippen')}?md=1",
            {
                f"pred_home_{self.match.id}": "2",
                f"pred_away_{self.match.id}": "1",
            },
        )

        self.assertEqual(response.status_code, 302)

        prediction = Prediction.objects.get(
            user=self.user,
            group=self.group,
            match=self.match,
        )

        self.assertEqual(prediction.pred_home, 2)
        self.assertEqual(prediction.pred_away, 1)
        self.assertIsNone(prediction.points)

    def test_bonus_tips_are_linked_from_tip_page_before_lock(self):
        response = self.client.get(
            f"{reverse('tippen')}?md=1"
        )
        bonus_url = reverse("bonus_tips")

        self.assertContains(
            response,
            "Pronósticos especiales",
        )
        self.assertEqual(
            response.content.decode().count(
                f'href="{bonus_url}"'
            ),
            1,
        )

    def test_bonus_tips_move_to_matchday_view_after_lock(self):
        Match.objects.filter(pk=self.match.pk).update(
            kickoff=(
                timezone.now()
                - timedelta(minutes=1)
            )
        )

        tip_response = self.client.get(
            f"{reverse('tippen')}?md=1"
        )
        bonus_response = self.client.get(
            reverse("bonus_tips")
        )

        self.assertNotContains(
            tip_response,
            f'href="{reverse("bonus_tips")}"',
        )
        self.assertRedirects(
            bonus_response,
            f"{reverse('spieltag')}?tab=bonus",
            fetch_redirect_response=False,
        )
