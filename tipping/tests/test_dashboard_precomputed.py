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


class DashboardPrecomputedStandingTests(
    TestCase
):
    def setUp(self):
        User = get_user_model()

        self.user_a = User.objects.create_user(
            username="dashboard-a",
            password="test-password-123",
        )

        self.user_b = User.objects.create_user(
            username="dashboard-b",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Dashboard-Testturnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Dashboard-Testgruppe",
            owner=self.user_a,
        )

        GroupMembership.objects.create(
            user=self.user_a,
            group=self.group,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.user_b,
            group=self.group,
            is_creator=False,
        )

        # Der zukünftige Anstoß sorgt zunächst dafür,
        # dass die Bonuspunkte noch nicht sichtbar sind.
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

        # QuerySet.update() wird bewusst verwendet,
        # damit die Ergebnis-Signale die für diesen Test
        # manuell gesetzten Read-Model-Werte nicht ändern.
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
            username="dashboard-a",
            password="test-password-123",
        )

        session = self.client.session
        session["active_group_id"] = (
            self.group.id
        )
        session.save()

    def get_dashboard(self):
        return self.client.get(
            reverse("dashboard")
        )

    def test_dashboard_uses_match_points_before_bonus_reveal(
        self,
    ):
        response = self.get_dashboard()

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertFalse(
            response.context[
                "bonus_reveal"
            ]
        )

        # Die gespeicherten 10 Bonuspunkte dürfen
        # vor der Freigabe noch nicht berücksichtigt
        # werden.
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
            2,
        )

        self.assertEqual(
            response.context[
                "exact_predictions"
            ],
            1,
        )

        self.assertEqual(
            response.context[
                "last_matchday_points"
            ],
            5,
        )

        rows_by_username = {
            row["user"].username: row
            for row in response.context[
                "mini_table_rows"
            ]
        }

        current_row = rows_by_username[
            "dashboard-a"
        ]

        self.assertEqual(
            current_row["total"],
            5,
        )

        self.assertEqual(
            current_row["bonus"],
            0,
        )

    def test_dashboard_uses_total_points_after_bonus_reveal(
        self,
    ):
        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
        )

        response = self.get_dashboard()

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            response.context[
                "bonus_reveal"
            ]
        )

        self.assertEqual(
            response.context[
                "user_total_points"
            ],
            15,
        )

        self.assertEqual(
            response.context[
                "user_position"
            ],
            1,
        )

        rows_by_username = {
            row["user"].username: row
            for row in response.context[
                "mini_table_rows"
            ]
        }

        current_row = rows_by_username[
            "dashboard-a"
        ]

        self.assertEqual(
            current_row["total"],
            15,
        )

        self.assertEqual(
            current_row["bonus"],
            10,
        )
