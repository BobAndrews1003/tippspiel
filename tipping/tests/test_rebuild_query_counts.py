from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    Match,
    Prediction,
    Tournament,
)
from tipping.result_processing import (
    process_match_change,
)
from tipping.standings import (
    rebuild_group_bonus_points,
    rebuild_group_standing,
    rebuild_group_timeline,
    rebuild_matchday_scores,
)


class RebuildQueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.small = cls.create_scenario(
            prefix="rebuild-small",
            member_count=3,
        )

        cls.large = cls.create_scenario(
            prefix="rebuild-large",
            member_count=120,
        )

    @classmethod
    def create_scenario(
        cls,
        *,
        prefix,
        member_count,
    ):
        User = get_user_model()

        owner = User.objects.create(
            username=f"{prefix}-owner",
        )

        tournament = Tournament.objects.create(
            name=f"{prefix}-tournament",
        )

        group = Group.objects.create(
            tournament=tournament,
            name=f"{prefix}-group",
            owner=owner,
        )

        extra_usernames = [
            f"{prefix}-user-{index:03d}"
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

        matches = []

        for matchday in range(1, 6):
            match = Match.objects.create(
                tournament=tournament,
                home_team=(
                    f"{prefix}-home-{matchday}"
                ),
                away_team=(
                    f"{prefix}-away-{matchday}"
                ),
                kickoff=(
                    timezone.now()
                    - timedelta(
                        days=6 - matchday
                    )
                ),
                matchday=matchday,
            )

            # Ergebnis setzen, ohne das Match-Signal
            # und damit ohne automatischen Rebuild.
            Match.objects.filter(
                pk=match.pk,
            ).update(
                home_score=2,
                away_score=1,
            )

            match.refresh_from_db()
            matches.append(match)

        Prediction.objects.bulk_create(
            [
                Prediction(
                    group=group,
                    user=user,
                    match=match,
                    pred_home=2,
                    pred_away=1,
                    points=4,
                )
                for user in users
                for match in matches
            ],
            batch_size=1000,
        )

        # Konsistenten Ausgangszustand herstellen.
        for match in matches:
            rebuild_matchday_scores(
                group_id=group.id,
                matchday=match.matchday,
            )

        rebuild_group_timeline(
            group_id=group.id,
        )

        rebuild_group_bonus_points(
            group_id=group.id,
        )

        return {
            "group": group,
            "matches": matches,
        }

    def count_queries(
        self,
        callback,
    ):
        # Aufwärmaufruf außerhalb der Messung.
        # Alle Rebuild-Funktionen sind idempotent.
        callback()

        with CaptureQueriesContext(
            connection
        ) as captured_queries:
            callback()

        return len(captured_queries)

    def assert_query_growth_is_bounded(
        self,
        *,
        label,
        small_callback,
        large_callback,
        tolerance=2,
    ):
        small_count = self.count_queries(
            small_callback
        )

        large_count = self.count_queries(
            large_callback
        )

        self.assertLessEqual(
            large_count,
            small_count + tolerance,
            msg=(
                f"{label}: Die Zahl der Abfragen "
                f"wächst mit der Gruppengröße. "
                f"Klein={small_count}, "
                f"groß={large_count}."
            ),
        )

    def test_matchday_score_query_count_is_bounded(
        self,
    ):
        self.assert_query_growth_is_bounded(
            label="MatchdayScore-Rebuild",
            small_callback=lambda: (
                rebuild_matchday_scores(
                    group_id=(
                        self.small["group"].id
                    ),
                    matchday=5,
                )
            ),
            large_callback=lambda: (
                rebuild_matchday_scores(
                    group_id=(
                        self.large["group"].id
                    ),
                    matchday=5,
                )
            ),
        )

    def test_timeline_query_count_is_bounded(
        self,
    ):
        self.assert_query_growth_is_bounded(
            label="Timeline-Rebuild",
            small_callback=lambda: (
                rebuild_group_timeline(
                    group_id=(
                        self.small["group"].id
                    ),
                    start_matchday=3,
                )
            ),
            large_callback=lambda: (
                rebuild_group_timeline(
                    group_id=(
                        self.large["group"].id
                    ),
                    start_matchday=3,
                )
            ),
        )

    def test_group_standing_query_count_is_bounded(
        self,
    ):
        self.assert_query_growth_is_bounded(
            label="GroupStanding-Rebuild",
            small_callback=lambda: (
                rebuild_group_standing(
                    group_id=(
                        self.small["group"].id
                    ),
                )
            ),
            large_callback=lambda: (
                rebuild_group_standing(
                    group_id=(
                        self.large["group"].id
                    ),
                )
            ),
        )

    def test_bonus_query_count_is_bounded(
        self,
    ):
        self.assert_query_growth_is_bounded(
            label="Bonus-Rebuild",
            small_callback=lambda: (
                rebuild_group_bonus_points(
                    group_id=(
                        self.small["group"].id
                    ),
                )
            ),
            large_callback=lambda: (
                rebuild_group_bonus_points(
                    group_id=(
                        self.large["group"].id
                    ),
                )
            ),
        )

    def test_complete_match_processing_is_bounded(
        self,
    ):
        small_match = self.small[
            "matches"
        ][-1]

        large_match = self.large[
            "matches"
        ][-1]

        self.assert_query_growth_is_bounded(
            label="Vollständige Ergebnisverarbeitung",
            small_callback=lambda: (
                process_match_change(
                    match_id=small_match.id,
                    previous_matchday=(
                        small_match.matchday
                    ),
                    rebuild_bonus=False,
                )
            ),
            large_callback=lambda: (
                process_match_change(
                    match_id=large_match.id,
                    previous_matchday=(
                        large_match.matchday
                    ),
                    rebuild_bonus=False,
                )
            ),
        )
