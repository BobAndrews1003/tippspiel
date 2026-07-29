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


class TabellePrecomputedTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user_a = User.objects.create_user(
            username="tabelle-a",
            password="test-password-123",
        )

        self.user_b = User.objects.create_user(
            username="tabelle-b",
            password="test-password-123",
        )

        self.user_c = User.objects.create_user(
            username="tabelle-c",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Tabellen-Testturnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Tabellen-Testgruppe",
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

        GroupMembership.objects.create(
            group=self.group,
            user=self.user_c,
            is_creator=False,
        )

        self.matchday_1 = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                + timedelta(days=1)
            ),
            matchday=1,
        )

        self.matchday_2 = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=(
                timezone.now()
                + timedelta(days=2)
            ),
            matchday=2,
        )

        # Die Ergebnissignale werden bewusst umgangen.
        # Dieser Test setzt das vorberechnete Read Model
        # gezielt manuell.
        Match.objects.filter(
            pk__in=[
                self.matchday_1.id,
                self.matchday_2.id,
            ]
        ).update(
            home_score=2,
            away_score=1,
        )

        score_data = [
            # Nutzer A: verbessert sich von Rang 3 auf 2.
            (
                self.user_a,
                1,
                0,
                0,
                3,
                None,
            ),
            (
                self.user_a,
                2,
                9,
                9,
                2,
                1,
            ),

            # Nutzer B bleibt auf Rang 1.
            (
                self.user_b,
                1,
                7,
                7,
                1,
                None,
            ),
            (
                self.user_b,
                2,
                5,
                12,
                1,
                0,
            ),

            # Nutzer C fällt von Rang 2 auf 3.
            (
                self.user_c,
                1,
                5,
                5,
                2,
                None,
            ),
            (
                self.user_c,
                2,
                0,
                5,
                3,
                -1,
            ),
        ]

        for (
            user,
            matchday,
            points,
            cumulative_points,
            rank,
            rank_change,
        ) in score_data:
            MatchdayScore.objects.create(
                group=self.group,
                user=user,
                matchday=matchday,
                points=points,
                cumulative_points=(
                    cumulative_points
                ),
                rank=rank,
                rank_change=rank_change,
            )

        GroupStanding.objects.create(
            group=self.group,
            user=self.user_a,
            match_points=9,
            bonus_points=10,
            total_points=19,
        )

        GroupStanding.objects.create(
            group=self.group,
            user=self.user_b,
            match_points=12,
            bonus_points=0,
            total_points=12,
        )

        GroupStanding.objects.create(
            group=self.group,
            user=self.user_c,
            match_points=5,
            bonus_points=0,
            total_points=5,
        )

        self.client.login(
            username="tabelle-a",
            password="test-password-123",
        )

        session = self.client.session
        session["active_group_id"] = (
            self.group.id
        )
        session.save()

    def get_table(self, **parameters):
        return self.client.get(
            reverse("tabelle"),
            parameters,
        )

    def rows_by_username(self, response):
        return {
            row["user"].username: row
            for row in response.context[
                "table_rows"
            ]
        }

    def test_mdpoints_uses_matchday_scores(
        self,
    ):
        response = self.get_table(
            view="mdpoints",
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

        rows = response.context[
            "table_rows"
        ]

        # Vor Bonusfreigabe erfolgt die Sortierung
        # ausschließlich nach den normalen Punkten.
        self.assertEqual(
            [
                row["user"].username
                for row in rows
            ],
            [
                "tabelle-b",
                "tabelle-a",
                "tabelle-c",
            ],
        )

        rows_by_user = self.rows_by_username(
            response
        )

        self.assertEqual(
            rows_by_user[
                "tabelle-a"
            ]["cells"],
            [
                0,
                9,
            ],
        )

        self.assertEqual(
            rows_by_user[
                "tabelle-b"
            ]["cells"],
            [
                7,
                5,
            ],
        )

        self.assertEqual(
            rows_by_user[
                "tabelle-a"
            ]["total"],
            9,
        )

        self.assertIsNone(
            rows_by_user[
                "tabelle-a"
            ]["bonus"]
        )

    def test_ranks_use_precomputed_values(
        self,
    ):
        response = self.get_table(
            view="ranks",
        )

        rows = self.rows_by_username(
            response
        )

        self.assertEqual(
            rows["tabelle-a"]["cells"],
            [
                3,
                2,
            ],
        )

        self.assertEqual(
            rows["tabelle-b"]["cells"],
            [
                1,
                1,
            ],
        )

        self.assertEqual(
            rows["tabelle-c"]["cells"],
            [
                2,
                3,
            ],
        )

    def test_rank_changes_use_precomputed_values(
        self,
    ):
        response = self.get_table(
            view="rankdiff",
        )

        rows = self.rows_by_username(
            response
        )

        self.assertEqual(
            rows["tabelle-a"]["cells"],
            [
                None,
                1,
            ],
        )

        self.assertEqual(
            rows["tabelle-b"]["cells"],
            [
                None,
                0,
            ],
        )

        self.assertEqual(
            rows["tabelle-c"]["cells"],
            [
                None,
                -1,
            ],
        )

    def test_bonus_and_total_are_used_after_reveal(
        self,
    ):
        Match.objects.filter(
            tournament=self.tournament,
        ).update(
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
        )

        response = self.get_table(
            view="mdpoints",
        )

        self.assertTrue(
            response.context[
                "bonus_reveal"
            ]
        )

        rows = response.context[
            "table_rows"
        ]

        # Mit freigegebenem Bonus überholt A den
        # vorher führenden Nutzer B.
        self.assertEqual(
            [
                row["user"].username
                for row in rows
            ],
            [
                "tabelle-a",
                "tabelle-b",
                "tabelle-c",
            ],
        )

        rows_by_user = self.rows_by_username(
            response
        )

        self.assertEqual(
            rows_by_user[
                "tabelle-a"
            ]["bonus"],
            10,
        )

        self.assertEqual(
            rows_by_user[
                "tabelle-a"
            ]["total"],
            19,
        )

        self.assertEqual(
            rows_by_user[
                "tabelle-b"
            ]["total"],
            12,
        )
