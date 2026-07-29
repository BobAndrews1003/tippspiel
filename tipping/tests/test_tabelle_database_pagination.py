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
from tipping.views import GROUP_PAGE_SIZE


class TabelleDatabasePaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.owner = User.objects.create_user(
            username="table-owner",
            password="test-password-123",
        )

        cls.tournament = Tournament.objects.create(
            name="Tabellen-Pagination-Turnier",
        )

        cls.group = Group.objects.create(
            tournament=cls.tournament,
            name="Tabellen-Pagination-Gruppe",
            owner=cls.owner,
        )

        extra_users = [
            User(
                username=(
                    f"table-user-{index:03d}"
                )
            )
            for index in range(
                1,
                GROUP_PAGE_SIZE + 6,
            )
        ]

        User.objects.bulk_create(
            extra_users,
            batch_size=500,
        )

        extra_users = list(
            User.objects
            .filter(
                username__startswith=(
                    "table-user-"
                )
            )
            .order_by("username")
        )

        cls.users = [
            cls.owner,
            *extra_users,
        ]

        GroupMembership.objects.bulk_create(
            [
                GroupMembership(
                    group=cls.group,
                    user=user,
                    is_creator=(
                        user.id
                        == cls.owner.id
                    ),
                )
                for user in cls.users
            ],
            batch_size=500,
        )

        user_count = len(cls.users)

        GroupStanding.objects.bulk_create(
            [
                GroupStanding(
                    group=cls.group,
                    user=user,
                    match_points=(
                        user_count - index
                    ),
                    bonus_points=0,
                    total_points=(
                        user_count - index
                    ),
                    exact_predictions=0,
                )
                for index, user in enumerate(
                    cls.users
                )
            ],
            batch_size=500,
        )

        cls.match = Match.objects.create(
            tournament=cls.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                + timedelta(days=1)
            ),
            matchday=1,
        )

        # Ergebnis setzen, ohne das Match-Signal
        # und einen vollständigen Rebuild auszulösen.
        Match.objects.filter(
            pk=cls.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

    def setUp(self):
        self.client.force_login(
            self.owner
        )

        session = self.client.session
        session[
            "active_group_id"
        ] = self.group.id
        session.save()

    def get_table(self, **parameters):
        query = {
            "view": "mdpoints",
            "count": 8,
        }

        query.update(parameters)

        return self.client.get(
            reverse("tabelle"),
            query,
        )

    def test_second_page_contains_only_second_page_users(
        self,
    ):
        response = self.get_table(
            page=2,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        page_obj = response.context[
            "page_obj"
        ]

        rows = response.context[
            "table_rows"
        ]

        self.assertEqual(
            page_obj.number,
            2,
        )

        self.assertEqual(
            page_obj.paginator.count,
            len(self.users),
        )

        expected_users = self.users[
            GROUP_PAGE_SIZE:
        ]

        self.assertEqual(
            [
                row["user"].id
                for row in rows
            ],
            [
                user.id
                for user in expected_users
            ],
        )

    def test_equal_points_are_sorted_by_username(
        self,
    ):
        tied_users = [
            self.users[3],
            self.users[1],
            self.users[2],
        ]

        GroupStanding.objects.filter(
            group=self.group,
            user__in=tied_users,
        ).update(
            match_points=999,
            total_points=999,
        )

        response = self.get_table()

        rows = response.context[
            "table_rows"
        ]

        expected_usernames = sorted(
            user.username
            for user in tied_users
        )

        self.assertEqual(
            [
                row["user"].username
                for row in rows[:3]
            ],
            expected_usernames,
        )

    def test_hidden_bonus_does_not_change_visible_order(
        self,
    ):
        lower_match_points_user = (
            self.users[2]
        )

        higher_match_points_user = (
            self.users[3]
        )

        # Dieser Nutzer hätte nach total_points deutlich
        # mehr Punkte. Vor der Bonusfreigabe darf das seine
        # sichtbare Position aber nicht verbessern.
        GroupStanding.objects.filter(
            group=self.group,
            user=lower_match_points_user,
        ).update(
            match_points=500,
            bonus_points=1000,
            total_points=1500,
        )

        GroupStanding.objects.filter(
            group=self.group,
            user=higher_match_points_user,
        ).update(
            match_points=600,
            bonus_points=0,
            total_points=600,
        )

        response = self.get_table()

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

        visible_user_ids = [
            row["user"].id
            for row in rows
        ]

        self.assertIn(
            lower_match_points_user.id,
            visible_user_ids,
        )

        self.assertIn(
            higher_match_points_user.id,
            visible_user_ids,
        )

        # Vor der Bonusfreigabe zählt 600 > 500.
        # Bei einer falschen Sortierung nach total_points
        # würde der Nutzer mit 1500 Punkten vorne stehen.
        self.assertLess(
            visible_user_ids.index(
                higher_match_points_user.id
            ),
            visible_user_ids.index(
                lower_match_points_user.id
            ),
        )
