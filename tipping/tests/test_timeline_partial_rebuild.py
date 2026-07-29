from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    MatchdayScore,
    Tournament,
)
from tipping.standings import (
    rebuild_group_timeline,
)


class TimelinePartialRebuildTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user_a = User.objects.create_user(
            username="timeline-alpha",
            password="test-password-123",
        )

        self.user_b = User.objects.create_user(
            username="timeline-beta",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Timeline-Teil-Rebuild-Turnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Timeline-Teil-Rebuild-Gruppe",
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
        )

        points = {
            1: {
                self.user_a.id: 4,
                self.user_b.id: 0,
            },
            2: {
                self.user_a.id: 0,
                self.user_b.id: 4,
            },
            3: {
                self.user_a.id: 2,
                self.user_b.id: 0,
            },
        }

        MatchdayScore.objects.bulk_create(
            [
                MatchdayScore(
                    group=self.group,
                    user_id=user_id,
                    matchday=matchday,
                    points=user_points,
                    exact_predictions=0,
                )
                for matchday, values
                in points.items()
                for user_id, user_points
                in values.items()
            ]
        )

        rebuild_group_timeline(
            group_id=self.group.id,
            start_matchday=1,
        )

    def test_partial_rebuild_uses_previous_cumulative_state(
        self,
    ):
        unchanged_time = (
            timezone.now()
            - timedelta(days=10)
        )

        MatchdayScore.objects.filter(
            group=self.group,
            matchday__lt=3,
        ).update(
            updated_at=unchanged_time,
        )

        # Spieltag 3 nachträglich verändern.
        MatchdayScore.objects.filter(
            group=self.group,
            user=self.user_a,
            matchday=3,
        ).update(
            points=0,
        )

        MatchdayScore.objects.filter(
            group=self.group,
            user=self.user_b,
            matchday=3,
        ).update(
            points=4,
        )

        updated_rows = rebuild_group_timeline(
            group_id=self.group.id,
            start_matchday=3,
        )

        self.assertEqual(
            updated_rows,
            2,
        )

        earlier_rows = list(
            MatchdayScore.objects
            .filter(
                group=self.group,
                matchday__lt=3,
            )
            .order_by(
                "matchday",
                "user_id",
            )
        )

        self.assertTrue(
            all(
                row.updated_at
                == unchanged_time
                for row in earlier_rows
            )
        )

        score_a = MatchdayScore.objects.get(
            group=self.group,
            user=self.user_a,
            matchday=3,
        )

        score_b = MatchdayScore.objects.get(
            group=self.group,
            user=self.user_b,
            matchday=3,
        )

        # Nach Spieltag 2 hatten beide vier Punkte und Rang 1.
        # Am dritten Spieltag erhält nur Nutzer B vier Punkte.
        self.assertEqual(
            score_a.cumulative_points,
            4,
        )

        self.assertEqual(
            score_b.cumulative_points,
            8,
        )

        self.assertEqual(
            score_a.rank,
            2,
        )

        self.assertEqual(
            score_b.rank,
            1,
        )

        self.assertEqual(
            score_a.rank_change,
            -1,
        )

        self.assertEqual(
            score_b.rank_change,
            0,
        )

    def test_full_rebuild_still_updates_all_rows(
        self,
    ):
        updated_rows = rebuild_group_timeline(
            group_id=self.group.id,
            start_matchday=1,
        )

        self.assertEqual(
            updated_rows,
            6,
        )
