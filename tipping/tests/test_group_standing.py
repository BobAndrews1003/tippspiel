from django.contrib.auth import get_user_model
from django.test import TestCase

from tipping.models import (
    Group,
    GroupMembership,
    GroupStanding,
    MatchdayScore,
    Tournament,
)
from tipping.standings import rebuild_group_standing


class RebuildGroupStandingTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.creator = User.objects.create_user(
            username="standing-creator",
            password="test-password-123",
        )

        self.second_user = User.objects.create_user(
            username="standing-second",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Standing-Testturnier",
        )

        self.group_a = Group.objects.create(
            tournament=self.tournament,
            name="Standing Gruppe A",
            owner=self.creator,
        )

        self.group_b = Group.objects.create(
            tournament=self.tournament,
            name="Standing Gruppe B",
            owner=self.creator,
        )

        GroupMembership.objects.create(
            user=self.creator,
            group=self.group_a,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.second_user,
            group=self.group_a,
        )

        GroupMembership.objects.create(
            user=self.creator,
            group=self.group_b,
            is_creator=True,
        )

        # Gruppe A:
        # creator = 6 + 4 = 10 Punkte
        # second_user = 3 Punkte

        MatchdayScore.objects.create(
            group=self.group_a,
            user=self.creator,
            matchday=1,
            points=6,
            exact_predictions=1,
        )

        MatchdayScore.objects.create(
            group=self.group_a,
            user=self.creator,
            matchday=2,
            points=4,
            exact_predictions=1,
        )

        MatchdayScore.objects.create(
            group=self.group_a,
            user=self.second_user,
            matchday=1,
            points=3,
            exact_predictions=0,
        )

        # Getrennter Punktestand in Gruppe B.
        MatchdayScore.objects.create(
            group=self.group_b,
            user=self.creator,
            matchday=1,
            points=2,
            exact_predictions=0,
        )

    def test_rebuild_creates_correct_standings(
        self,
    ):
        count = rebuild_group_standing(
            group_id=self.group_a.id,
        )

        self.assertEqual(count, 2)

        creator_standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.creator,
        )

        second_standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.second_user,
        )

        self.assertEqual(
            creator_standing.match_points,
            10,
        )

        self.assertEqual(
            creator_standing.bonus_points,
            0,
        )

        self.assertEqual(
            creator_standing.total_points,
            10,
        )

        self.assertEqual(
            creator_standing.exact_predictions,
            2,
        )

        self.assertEqual(
            second_standing.match_points,
            3,
        )

        self.assertEqual(
            second_standing.total_points,
            3,
        )

    def test_groups_are_strictly_separated(self):
        rebuild_group_standing(
            group_id=self.group_a.id,
        )

        self.assertFalse(
            GroupStanding.objects.filter(
                group=self.group_b,
            ).exists()
        )

        group_a_standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.creator,
        )

        self.assertEqual(
            group_a_standing.match_points,
            10,
        )

        rebuild_group_standing(
            group_id=self.group_b.id,
        )

        group_b_standing = GroupStanding.objects.get(
            group=self.group_b,
            user=self.creator,
        )

        self.assertEqual(
            group_b_standing.match_points,
            2,
        )

        group_a_standing.refresh_from_db()

        self.assertEqual(
            group_a_standing.match_points,
            10,
        )

    def test_existing_bonus_points_are_preserved(
        self,
    ):
        GroupStanding.objects.create(
            group=self.group_a,
            user=self.creator,
            match_points=0,
            bonus_points=5,
            total_points=5,
            exact_predictions=0,
        )

        rebuild_group_standing(
            group_id=self.group_a.id,
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.creator,
        )

        self.assertEqual(
            standing.match_points,
            10,
        )

        self.assertEqual(
            standing.bonus_points,
            5,
        )

        self.assertEqual(
            standing.total_points,
            15,
        )

    def test_rebuild_is_idempotent(self):
        first_count = rebuild_group_standing(
            group_id=self.group_a.id,
        )

        second_count = rebuild_group_standing(
            group_id=self.group_a.id,
        )

        self.assertEqual(first_count, 2)
        self.assertEqual(second_count, 2)

        self.assertEqual(
            GroupStanding.objects.filter(
                group=self.group_a,
            ).count(),
            2,
        )

    def test_rebuild_copies_latest_matchday_wins(self):
        MatchdayScore.objects.filter(
            group=self.group_a,
            user=self.creator,
            matchday=1,
        ).update(
            cumulative_matchday_wins=1,
        )
        MatchdayScore.objects.filter(
            group=self.group_a,
            user=self.creator,
            matchday=2,
        ).update(
            cumulative_matchday_wins=2,
        )

        rebuild_group_standing(
            group_id=self.group_a.id,
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.creator,
        )
        self.assertEqual(
            standing.matchday_wins,
            2,
        )

    def test_departed_members_are_removed(self):
        rebuild_group_standing(
            group_id=self.group_a.id,
        )

        self.assertTrue(
            GroupStanding.objects.filter(
                group=self.group_a,
                user=self.second_user,
            ).exists()
        )

        GroupMembership.objects.filter(
            group=self.group_a,
            user=self.second_user,
        ).delete()

        rebuild_group_standing(
            group_id=self.group_a.id,
        )

        self.assertFalse(
            GroupStanding.objects.filter(
                group=self.group_a,
                user=self.second_user,
            ).exists()
        )
