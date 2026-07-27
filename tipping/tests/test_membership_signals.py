from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
)
from tipping.standings import (
    rebuild_group_bonus_points,
    rebuild_group_timeline,
    rebuild_matchday_scores,
)


class MembershipSignalTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user_a = User.objects.create_user(
            username="membership-a",
            password="test-password-123",
        )

        self.user_b = User.objects.create_user(
            username="membership-b",
            password="test-password-123",
        )

        self.user_c = User.objects.create_user(
            username="membership-c",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Membership-Testturnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Membership-Testgruppe",
            owner=self.user_a,
        )

        self.membership_a = (
            GroupMembership.objects.create(
                group=self.group,
                user=self.user_a,
                is_creator=True,
            )
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

        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        Prediction.objects.create(
            group=self.group,
            user=self.user_a,
            match=self.match,
            pred_home=2,
            pred_away=1,
            points=4,
        )

        rebuild_matchday_scores(
            group_id=self.group.id,
            matchday=1,
        )

        rebuild_group_timeline(
            group_id=self.group.id,
            start_matchday=1,
        )

        rebuild_group_bonus_points(
            group_id=self.group.id,
        )

    def test_join_creates_zero_score_and_standing(
        self,
    ):
        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            GroupMembership.objects.create(
                group=self.group,
                user=self.user_b,
                is_creator=False,
            )

        score = MatchdayScore.objects.get(
            group=self.group,
            user=self.user_b,
            matchday=1,
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user_b,
        )

        self.assertEqual(score.points, 0)
        self.assertEqual(
            score.cumulative_points,
            0,
        )
        self.assertEqual(score.rank, 2)

        self.assertEqual(
            standing.match_points,
            0,
        )
        self.assertEqual(
            standing.total_points,
            0,
        )

    def test_join_rebuilds_existing_member_rank(
        self,
    ):
        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            GroupMembership.objects.create(
                group=self.group,
                user=self.user_b,
                is_creator=False,
            )

        score_a = MatchdayScore.objects.get(
            group=self.group,
            user=self.user_a,
            matchday=1,
        )

        self.assertEqual(score_a.rank, 1)

    def test_delete_removes_departed_member_rows(
        self,
    ):
        membership_b = (
            GroupMembership.objects.create(
                group=self.group,
                user=self.user_b,
                is_creator=False,
            )
        )

        rebuild_matchday_scores(
            group_id=self.group.id,
            matchday=1,
        )

        rebuild_group_timeline(
            group_id=self.group.id,
            start_matchday=1,
        )

        rebuild_group_bonus_points(
            group_id=self.group.id,
        )

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            membership_b.delete()

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group,
                user=self.user_b,
            ).exists()
        )

        self.assertFalse(
            GroupStanding.objects.filter(
                group=self.group,
                user=self.user_b,
            ).exists()
        )

    def test_delete_rebuilds_competition_ranks(
        self,
    ):
        membership_b = (
            GroupMembership.objects.create(
                group=self.group,
                user=self.user_b,
                is_creator=False,
            )
        )

        membership_c = (
            GroupMembership.objects.create(
                group=self.group,
                user=self.user_c,
                is_creator=False,
            )
        )

        Prediction.objects.create(
            group=self.group,
            user=self.user_b,
            match=self.match,
            pred_home=2,
            pred_away=1,
            points=4,
        )

        rebuild_matchday_scores(
            group_id=self.group.id,
            matchday=1,
        )

        rebuild_group_timeline(
            group_id=self.group.id,
            start_matchday=1,
        )

        score_c_before = MatchdayScore.objects.get(
            group=self.group,
            user=self.user_c,
            matchday=1,
        )

        # A und B sind mit 4 Punkten auf Rang 1.
        # C steht deshalb im Wettbewerbssystem auf Rang 3.
        self.assertEqual(
            score_c_before.rank,
            3,
        )

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            membership_b.delete()

        score_c_after = MatchdayScore.objects.get(
            group=self.group,
            user=self.user_c,
            matchday=1,
        )

        self.assertEqual(
            score_c_after.rank,
            2,
        )

        # Verhindert eine Warnung über die lokale Variable
        # und dokumentiert, dass C weiterhin Mitglied ist.
        self.assertTrue(
            GroupMembership.objects.filter(
                pk=membership_c.pk,
            ).exists()
        )

    def test_last_member_delete_cleans_read_model(
        self,
    ):
        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.membership_a.delete()

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group,
            ).exists()
        )

        self.assertFalse(
            GroupStanding.objects.filter(
                group=self.group,
            ).exists()
        )
