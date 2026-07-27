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
    Tournament,
)


class DashboardDatabaseRankingTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.current_user = User.objects.create_user(
            username="ranking-current",
            password="test-password-123",
        )

        self.first_user = User.objects.create_user(
            username="ranking-first",
            password="test-password-123",
        )

        self.alpha_user = User.objects.create_user(
            username="ranking-alpha",
            password="test-password-123",
        )

        self.beta_user = User.objects.create_user(
            username="ranking-beta",
            password="test-password-123",
        )

        self.last_user = User.objects.create_user(
            username="ranking-last",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Dashboard-DB-Ranking-Turnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Dashboard-DB-Ranking-Gruppe",
            owner=self.current_user,
        )

        users = [
            self.current_user,
            self.first_user,
            self.alpha_user,
            self.beta_user,
            self.last_user,
        ]

        for user in users:
            GroupMembership.objects.create(
                group=self.group,
                user=user,
                is_creator=(
                    user.id
                    == self.current_user.id
                ),
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

        # Ergebnis ohne Signal setzen.
        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        points_by_user = {
            self.first_user: 20,
            self.alpha_user: 15,
            self.beta_user: 15,
            self.current_user: 5,
            self.last_user: 0,
        }

        for user, points in points_by_user.items():
            GroupStanding.objects.create(
                group=self.group,
                user=user,
                match_points=points,
                bonus_points=0,
                total_points=points,
                exact_predictions=0,
            )

        self.client.login(
            username="ranking-current",
            password="test-password-123",
        )

        session = self.client.session
        session["active_group_id"] = self.group.id
        session.save()

    def get_dashboard(self):
        return self.client.get(
            reverse("dashboard")
        )

    def test_database_ranking_preserves_competition_positions(
        self,
    ):
        response = self.get_dashboard()

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.context[
                "participant_count"
            ],
            5,
        )

        self.assertEqual(
            response.context[
                "user_total_points"
            ],
            5,
        )

        self.assertEqual(
            response.context[
                "user_position"
            ],
            4,
        )

        rows = response.context[
            "mini_table_rows"
        ]

        self.assertEqual(
            [
                row["user"].username
                for row in rows
            ],
            [
                "ranking-first",
                "ranking-alpha",
                "ranking-beta",
                "ranking-current",
            ],
        )

        self.assertEqual(
            [
                row["position"]
                for row in rows
            ],
            [
                1,
                2,
                2,
                4,
            ],
        )

    def test_current_user_is_marked_as_extra_row(
        self,
    ):
        response = self.get_dashboard()

        current_row = next(
            row
            for row in response.context[
                "mini_table_rows"
            ]
            if row["user"].id
            == self.current_user.id
        )

        self.assertTrue(
            current_row[
                "is_current_user"
            ]
        )

        self.assertTrue(
            current_row[
                "is_extra"
            ]
        )
