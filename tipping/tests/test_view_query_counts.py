from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
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


class ViewQueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tournament = Tournament.objects.create(
            name="Query-Count-Testturnier",
        )

        cls.match = Match.objects.create(
            tournament=cls.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
            matchday=1,
        )

        # Signale bewusst umgehen. Die vorberechneten
        # Tabellen werden für den Test direkt erzeugt.
        Match.objects.filter(
            pk=cls.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        (
            cls.small_group,
            cls.small_owner,
        ) = cls.create_group_with_members(
            prefix="query-small",
            member_count=3,
        )

        (
            cls.large_group,
            cls.large_owner,
        ) = cls.create_group_with_members(
            prefix="query-large",
            member_count=120,
        )

    @classmethod
    def create_group_with_members(
        cls,
        *,
        prefix,
        member_count,
    ):
        User = get_user_model()

        owner = User.objects.create(
            username=f"{prefix}-owner",
        )

        group = Group.objects.create(
            tournament=cls.tournament,
            name=f"{prefix}-group",
            owner=owner,
        )

        extra_usernames = [
            f"{prefix}-member-{index:03d}"
            for index in range(
                1,
                member_count,
            )
        ]

        User.objects.bulk_create(
            [
                User(username=username)
                for username in extra_usernames
            ],
            batch_size=500,
        )

        extra_users = list(
            User.objects
            .filter(
                username__in=extra_usernames,
            )
            .order_by("username")
        )

        users = [
            owner,
            *extra_users,
        ]

        GroupMembership.objects.bulk_create(
            [
                GroupMembership(
                    group=group,
                    user=user,
                    is_creator=(
                        user.id == owner.id
                    ),
                )
                for user in users
            ],
            batch_size=500,
        )

        standing_rows = []
        matchday_rows = []

        for index, user in enumerate(
            users,
            start=1,
        ):
            # Unterschiedliche Werte sorgen dafür,
            # dass Sortierung und Ranglistenaufbau
            # tatsächlich ausgeführt werden.
            points = (
                member_count
                - index
            )

            standing_rows.append(
                GroupStanding(
                    group=group,
                    user=user,
                    match_points=points,
                    bonus_points=0,
                    total_points=points,
                    exact_predictions=0,
                )
            )

            matchday_rows.append(
                MatchdayScore(
                    group=group,
                    user=user,
                    matchday=1,
                    points=points,
                    exact_predictions=0,
                    cumulative_points=points,
                    rank=index,
                    rank_change=None,
                )
            )

        GroupStanding.objects.bulk_create(
            standing_rows,
            batch_size=500,
        )

        MatchdayScore.objects.bulk_create(
            matchday_rows,
            batch_size=500,
        )

        return group, owner

    def count_view_queries(
        self,
        *,
        group,
        user,
        url,
    ):
        client = Client()

        client.force_login(user)

        session = client.session
        session["active_group_id"] = group.id
        session.save()

        # Erster Aufruf außerhalb der Messung:
        # URL-Auflösung, Templates und andere einmalige
        # Initialisierungen sollen das Ergebnis nicht
        # verfälschen.
        warmup_response = client.get(url)

        self.assertEqual(
            warmup_response.status_code,
            200,
        )

        with CaptureQueriesContext(
            connection
        ) as captured_queries:
            response = client.get(url)

        self.assertEqual(
            response.status_code,
            200,
        )

        return len(captured_queries)

    def assert_query_growth_is_bounded(
        self,
        *,
        url,
        view_name,
    ):
        small_count = self.count_view_queries(
            group=self.small_group,
            user=self.small_owner,
            url=url,
        )

        large_count = self.count_view_queries(
            group=self.large_group,
            user=self.large_owner,
            url=url,
        )

        self.assertLessEqual(
            large_count,
            small_count + 2,
            msg=(
                f"{view_name}: Die Abfragezahl wächst "
                f"zu stark mit der Gruppengröße. "
                f"Kleine Gruppe: {small_count}, "
                f"große Gruppe: {large_count}."
            ),
        )

    def test_dashboard_query_count_does_not_scale(
        self,
    ):
        self.assert_query_growth_is_bounded(
            url=reverse("dashboard"),
            view_name="Dashboard",
        )

    def test_spieltag_query_count_does_not_scale(
        self,
    ):
        self.assert_query_growth_is_bounded(
            url=(
                reverse("spieltag")
                + "?tab=matches"
            ),
            view_name="Spieltag",
        )

    def test_tabelle_query_count_does_not_scale(
        self,
    ):
        self.assert_query_growth_is_bounded(
            url=(
                reverse("tabelle")
                + "?view=mdpoints&count=8"
            ),
            view_name="Tabelle",
        )
