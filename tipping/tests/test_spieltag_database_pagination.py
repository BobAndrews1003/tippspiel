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
from tipping.views import GROUP_PAGE_SIZE


class SpieltagDatabasePaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.owner = User.objects.create_user(
            username="zzzz-spieltag-owner",
            password="test-password-123",
        )

        cls.tournament = Tournament.objects.create(
            name="Spieltag-Pagination-Turnier",
        )

        cls.group = Group.objects.create(
            tournament=cls.tournament,
            name="Spieltag-Pagination-Gruppe",
            owner=cls.owner,
        )

        User.objects.bulk_create(
            [
                User(
                    username=(
                        f"spieltag-user-{index:03d}"
                    )
                )
                for index in range(
                    1,
                    GROUP_PAGE_SIZE + 6,
                )
            ],
            batch_size=500,
        )

        extra_users = list(
            User.objects
            .filter(
                username__startswith=(
                    "spieltag-user-"
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

        # Der zukünftige Anstoß hält Bonustipps zunächst
        # verborgen. Das Ergebnis macht Spieltag 1 zugleich
        # zu einem ausgewerteten Spieltag.
        cls.match = Match.objects.create(
            tournament=cls.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                + timedelta(days=2)
            ),
            matchday=1,
        )

        # Signal bewusst umgehen.
        Match.objects.filter(
            pk=cls.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        user_count = len(cls.users)

        MatchdayScore.objects.bulk_create(
            [
                MatchdayScore(
                    group=cls.group,
                    user=user,
                    matchday=1,
                    points=(
                        user_count - index
                    ),
                    exact_predictions=0,
                    cumulative_points=(
                        user_count - index
                    ),
                    rank=index + 1,
                    rank_change=None,
                )
                for index, user in enumerate(
                    cls.users
                )
            ],
            batch_size=500,
        )

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

    def setUp(self):
        self.client.force_login(
            self.owner
        )

        session = self.client.session
        session[
            "active_group_id"
        ] = self.group.id
        session.save()

    def get_spieltag(
        self,
        *,
        tab="matches",
        page=1,
    ):
        return self.client.get(
            reverse("spieltag"),
            {
                "tab": tab,
                "md": 1,
                "page": page,
            },
        )

    def test_match_tab_second_page_contains_only_page_users(
        self,
    ):
        response = self.get_spieltag(
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

    def test_equal_matchday_points_are_sorted_by_username(
        self,
    ):
        tied_users = [
            self.users[3],
            self.users[1],
            self.users[2],
        ]

        MatchdayScore.objects.filter(
            group=self.group,
            user__in=tied_users,
            matchday=1,
        ).update(
            points=999,
        )

        response = self.get_spieltag()

        self.assertEqual(
            response.status_code,
            200,
        )

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

        self.assertEqual(
            [
                row["position"]
                for row in rows[:3]
            ],
            [
                1,
                1,
                1,
            ],
        )

    def test_hidden_bonus_places_current_user_first(
        self,
    ):
        response = self.get_spieltag(
            tab="bonus",
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
            "bonus_rows"
        ]

        self.assertTrue(rows)

        self.assertEqual(
            rows[0]["user"].id,
            self.owner.id,
        )

        self.assertTrue(
            rows[0]["reveal"]
        )

        self.assertContains(
            response,
            "Pronósticos especiales",
        )

    def test_revealed_bonus_is_sorted_in_database(
        self,
    ):
        first_bonus_user = self.users[2]
        second_bonus_user = self.users[3]

        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            )
        )

        GroupStanding.objects.filter(
            group=self.group,
            user=first_bonus_user,
        ).update(
            bonus_points=200,
            total_points=200,
        )

        GroupStanding.objects.filter(
            group=self.group,
            user=second_bonus_user,
        ).update(
            bonus_points=100,
            total_points=100,
        )

        response = self.get_spieltag(
            tab="bonus",
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

        rows = response.context[
            "bonus_rows"
        ]

        self.assertEqual(
            rows[0]["user"].id,
            first_bonus_user.id,
        )

        self.assertEqual(
            rows[0]["points"],
            200,
        )

        self.assertEqual(
            rows[1]["user"].id,
            second_bonus_user.id,
        )

        self.assertEqual(
            rows[1]["points"],
            100,
        )
