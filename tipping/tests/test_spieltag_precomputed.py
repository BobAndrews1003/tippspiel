from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
    Tournament,
)


class SpieltagPrecomputedTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user_a = User.objects.create_user(
            username="spieltag-a",
            password="test-password-123",
        )

        self.user_b = User.objects.create_user(
            username="spieltag-b",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Spieltag-Testturnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Spieltag-Testgruppe",
            owner=self.user_a,
        )

        GroupMembership.objects.create(
            group=self.group,
            user=self.user_a,
            is_creator=True,
        )

        GroupMembership.objects.create(
            group=self.group,
            user=self.user_b,
            is_creator=False,
        )

        self.match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
            matchday=1,
        )

        # Signale absichtlich umgehen. Die Read-Model-Werte
        # werden für diesen Test gezielt manuell gesetzt.
        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        MatchdayScore.objects.create(
            group=self.group,
            user=self.user_a,
            matchday=1,
            points=5,
            exact_predictions=1,
            cumulative_points=5,
            rank=2,
        )

        MatchdayScore.objects.create(
            group=self.group,
            user=self.user_b,
            matchday=1,
            points=7,
            exact_predictions=0,
            cumulative_points=7,
            rank=1,
        )

        GroupStanding.objects.create(
            group=self.group,
            user=self.user_a,
            match_points=5,
            bonus_points=10,
            total_points=15,
            exact_predictions=1,
        )

        GroupStanding.objects.create(
            group=self.group,
            user=self.user_b,
            match_points=7,
            bonus_points=0,
            total_points=7,
            exact_predictions=0,
        )

        self.client.login(
            username="spieltag-a",
            password="test-password-123",
        )

        session = self.client.session
        session["active_group_id"] = self.group.id
        session.save()

    def test_matches_tab_uses_matchday_score(
        self,
    ):
        response = self.client.get(
            reverse("spieltag")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        rows = response.context[
            "table_rows"
        ]

        self.assertEqual(
            [
                row["user"].username
                for row in rows
            ],
            [
                "spieltag-b",
                "spieltag-a",
            ],
        )

        rows_by_username = {
            row["user"].username: row
            for row in rows
        }

        self.assertEqual(
            rows_by_username[
                "spieltag-a"
            ]["total_points"],
            5,
        )

        self.assertEqual(
            rows_by_username[
                "spieltag-b"
            ]["total_points"],
            7,
        )

    def test_bonus_tab_uses_group_standing(
        self,
    ):
        response = self.client.get(
            reverse("spieltag"),
            {
                "tab": "bonus",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            response.context[
                "bonus_reveal"
            ]
        )

        rows_by_username = {
            row["user"].username: row
            for row in response.context[
                "bonus_rows"
            ]
        }

        self.assertEqual(
            rows_by_username[
                "spieltag-a"
            ]["points"],
            10,
        )

        self.assertEqual(
            rows_by_username[
                "spieltag-b"
            ]["points"],
            0,
        )

    def test_bonus_points_remain_hidden_before_reveal(
        self,
    ):
        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            kickoff=(
                timezone.now()
                + timedelta(days=1)
            ),
        )

        response = self.client.get(
            reverse("spieltag"),
            {
                "tab": "bonus",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertFalse(
            response.context[
                "bonus_reveal"
            ]
        )

        for row in response.context[
            "bonus_rows"
        ]:
            self.assertIsNone(
                row["points"]
            )
