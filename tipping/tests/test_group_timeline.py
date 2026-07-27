from django.contrib.auth import get_user_model
from django.test import TestCase

from tipping.models import (
    Group,
    GroupMembership,
    MatchdayScore,
    Tournament,
)
from tipping.standings import rebuild_group_timeline


class RebuildGroupTimelineTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user_a = User.objects.create_user(
            username="timeline-a",
            password="test-password-123",
        )

        self.user_b = User.objects.create_user(
            username="timeline-b",
            password="test-password-123",
        )

        self.user_c = User.objects.create_user(
            username="timeline-c",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Timeline-Testturnier",
        )

        self.group_a = Group.objects.create(
            tournament=self.tournament,
            name="Timeline Gruppe A",
            owner=self.user_a,
        )

        self.group_b = Group.objects.create(
            tournament=self.tournament,
            name="Timeline Gruppe B",
            owner=self.user_a,
        )

        GroupMembership.objects.create(
            user=self.user_a,
            group=self.group_a,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.user_b,
            group=self.group_a,
        )

        GroupMembership.objects.create(
            user=self.user_c,
            group=self.group_a,
        )

        GroupMembership.objects.create(
            user=self.user_a,
            group=self.group_b,
            is_creator=True,
        )

        # Spieltag 1:
        # A = 5 Punkte → Rang 1
        # B = 3 Punkte → Rang 2
        # C = 3 Punkte → Rang 2

        self.score_a_1 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_a,
            matchday=1,
            points=5,
        )

        self.score_b_1 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_b,
            matchday=1,
            points=3,
        )

        self.score_c_1 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_c,
            matchday=1,
            points=3,
        )

        # Spieltag 2:
        # kumuliert:
        # A = 5 → Rang 1
        # B = 5 → Rang 1
        # C = 3 → Rang 3

        self.score_a_2 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_a,
            matchday=2,
            points=0,
        )

        self.score_b_2 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_b,
            matchday=2,
            points=2,
        )

        self.score_c_2 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_c,
            matchday=2,
            points=0,
        )

        # Spieltag 3:
        # kumuliert:
        # C = 7 → Rang 1
        # A = 5 → Rang 2
        # B = 5 → Rang 2

        self.score_a_3 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_a,
            matchday=3,
            points=0,
        )

        self.score_b_3 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_b,
            matchday=3,
            points=0,
        )

        self.score_c_3 = MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_c,
            matchday=3,
            points=4,
        )

        MatchdayScore.objects.create(
            group=self.group_b,
            user=self.user_a,
            matchday=1,
            points=20,
        )

    def test_timeline_calculates_cumulative_points(
        self,
    ):
        count = rebuild_group_timeline(
            group_id=self.group_a.id,
        )

        self.assertEqual(count, 9)

        self.score_a_1.refresh_from_db()
        self.score_a_2.refresh_from_db()
        self.score_a_3.refresh_from_db()

        self.score_b_3.refresh_from_db()
        self.score_c_3.refresh_from_db()

        self.assertEqual(
            self.score_a_1.cumulative_points,
            5,
        )

        self.assertEqual(
            self.score_a_2.cumulative_points,
            5,
        )

        self.assertEqual(
            self.score_a_3.cumulative_points,
            5,
        )

        self.assertEqual(
            self.score_b_3.cumulative_points,
            5,
        )

        self.assertEqual(
            self.score_c_3.cumulative_points,
            7,
        )

    def test_timeline_uses_competition_ranking(
        self,
    ):
        rebuild_group_timeline(
            group_id=self.group_a.id,
        )

        self.score_a_1.refresh_from_db()
        self.score_b_1.refresh_from_db()
        self.score_c_1.refresh_from_db()

        self.assertEqual(self.score_a_1.rank, 1)
        self.assertEqual(self.score_b_1.rank, 2)
        self.assertEqual(self.score_c_1.rank, 2)

        self.score_a_2.refresh_from_db()
        self.score_b_2.refresh_from_db()
        self.score_c_2.refresh_from_db()

        self.assertEqual(self.score_a_2.rank, 1)
        self.assertEqual(self.score_b_2.rank, 1)
        self.assertEqual(self.score_c_2.rank, 3)

        self.score_a_3.refresh_from_db()
        self.score_b_3.refresh_from_db()
        self.score_c_3.refresh_from_db()

        self.assertEqual(self.score_c_3.rank, 1)
        self.assertEqual(self.score_a_3.rank, 2)
        self.assertEqual(self.score_b_3.rank, 2)

    def test_rank_changes_match_existing_logic(
        self,
    ):
        rebuild_group_timeline(
            group_id=self.group_a.id,
        )

        self.score_a_1.refresh_from_db()
        self.score_b_1.refresh_from_db()
        self.score_c_1.refresh_from_db()

        self.assertIsNone(
            self.score_a_1.rank_change
        )

        self.assertIsNone(
            self.score_b_1.rank_change
        )

        self.assertIsNone(
            self.score_c_1.rank_change
        )

        self.score_a_2.refresh_from_db()
        self.score_b_2.refresh_from_db()
        self.score_c_2.refresh_from_db()

        self.assertEqual(
            self.score_a_2.rank_change,
            0,
        )

        self.assertEqual(
            self.score_b_2.rank_change,
            1,
        )

        self.assertEqual(
            self.score_c_2.rank_change,
            -1,
        )

        self.score_a_3.refresh_from_db()
        self.score_b_3.refresh_from_db()
        self.score_c_3.refresh_from_db()

        self.assertEqual(
            self.score_a_3.rank_change,
            -1,
        )

        self.assertEqual(
            self.score_b_3.rank_change,
            -1,
        )

        self.assertEqual(
            self.score_c_3.rank_change,
            2,
        )

    def test_groups_are_strictly_separated(self):
        rebuild_group_timeline(
            group_id=self.group_a.id,
        )

        group_b_score = MatchdayScore.objects.get(
            group=self.group_b,
            user=self.user_a,
            matchday=1,
        )

        self.assertEqual(
            group_b_score.points,
            20,
        )

        self.assertEqual(
            group_b_score.cumulative_points,
            0,
        )

        self.assertIsNone(
            group_b_score.rank,
        )

    def test_partial_rebuild_starts_at_selected_matchday(
        self,
    ):
        rebuild_group_timeline(
            group_id=self.group_a.id,
        )

        self.score_b_2.points = 5
        self.score_b_2.save(
            update_fields=[
                "points",
            ],
        )

        count = rebuild_group_timeline(
            group_id=self.group_a.id,
            start_matchday=2,
        )

        self.assertEqual(count, 6)

        self.score_b_1.refresh_from_db()
        self.score_b_2.refresh_from_db()
        self.score_b_3.refresh_from_db()

        # Spieltag 1 bleibt unverändert.
        self.assertEqual(
            self.score_b_1.cumulative_points,
            3,
        )

        self.assertEqual(
            self.score_b_1.rank,
            2,
        )

        # Ab Spieltag 2 wird neu gerechnet.
        self.assertEqual(
            self.score_b_2.cumulative_points,
            8,
        )

        self.assertEqual(
            self.score_b_2.rank,
            1,
        )

        self.assertEqual(
            self.score_b_3.cumulative_points,
            8,
        )

        self.assertEqual(
            self.score_b_3.rank,
            1,
        )

    def test_rebuild_is_idempotent(self):
        first_count = rebuild_group_timeline(
            group_id=self.group_a.id,
        )

        second_count = rebuild_group_timeline(
            group_id=self.group_a.id,
        )

        self.assertEqual(first_count, 9)
        self.assertEqual(second_count, 9)

        self.assertEqual(
            MatchdayScore.objects.filter(
                group=self.group_a,
            ).count(),
            9,
        )

    def test_invalid_start_matchday_is_rejected(self):
        with self.assertRaises(ValueError):
            rebuild_group_timeline(
                group_id=self.group_a.id,
                start_matchday=0,
            )
