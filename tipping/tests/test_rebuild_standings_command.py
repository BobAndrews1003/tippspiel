from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
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


class RebuildStandingsCommandTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="command-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Command-Testturnier",
        )

        self.group_a = Group.objects.create(
            tournament=self.tournament,
            name="Command Gruppe A",
            owner=self.user,
        )

        self.group_b = Group.objects.create(
            tournament=self.tournament,
            name="Command Gruppe B",
            owner=self.user,
        )

        GroupMembership.objects.create(
            user=self.user,
            group=self.group_a,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.user,
            group=self.group_b,
            is_creator=True,
        )

        kickoff = (
            timezone.now()
            - timedelta(days=1)
        )

        self.match_1 = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=kickoff,
            matchday=1,
            home_score=2,
            away_score=1,
        )

        self.match_2 = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=kickoff,
            matchday=2,
            home_score=0,
            away_score=0,
        )

        Prediction.objects.create(
            user=self.user,
            group=self.group_a,
            match=self.match_1,
            pred_home=2,
            pred_away=1,
            points=4,
        )

        Prediction.objects.create(
            user=self.user,
            group=self.group_a,
            match=self.match_2,
            pred_home=1,
            pred_away=1,
            points=3,
        )

        Prediction.objects.create(
            user=self.user,
            group=self.group_b,
            match=self.match_1,
            pred_home=1,
            pred_away=0,
            points=2,
        )

    def test_command_rebuilds_only_selected_group(
        self,
    ):
        output = StringIO()

        call_command(
            "rebuild_standings",
            group_id=self.group_a.id,
            stdout=output,
        )

        score_1 = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.user,
            matchday=1,
        )

        score_2 = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.user,
            matchday=2,
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user,
        )

        self.assertEqual(score_1.points, 4)
        self.assertEqual(score_1.cumulative_points, 4)
        self.assertEqual(score_1.rank, 1)
        self.assertIsNone(score_1.rank_change)

        self.assertEqual(score_2.points, 3)
        self.assertEqual(score_2.cumulative_points, 7)
        self.assertEqual(score_2.rank, 1)
        self.assertEqual(score_2.rank_change, 0)

        self.assertEqual(
            standing.match_points,
            7,
        )

        self.assertEqual(
            standing.total_points,
            7,
        )

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group_b,
            ).exists()
        )

        self.assertFalse(
            GroupStanding.objects.filter(
                group=self.group_b,
            ).exists()
        )

    def test_command_is_idempotent(self):
        call_command(
            "rebuild_standings",
            group_id=self.group_a.id,
            stdout=StringIO(),
        )

        call_command(
            "rebuild_standings",
            group_id=self.group_a.id,
            stdout=StringIO(),
        )

        self.assertEqual(
            MatchdayScore.objects.filter(
                group=self.group_a,
            ).count(),
            2,
        )

        self.assertEqual(
            GroupStanding.objects.filter(
                group=self.group_a,
            ).count(),
            1,
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            7,
        )

    def test_command_rebuilds_all_groups(self):
        call_command(
            "rebuild_standings",
            stdout=StringIO(),
        )

        standing_a = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user,
        )

        standing_b = GroupStanding.objects.get(
            group=self.group_b,
            user=self.user,
        )

        self.assertEqual(
            standing_a.match_points,
            7,
        )

        self.assertEqual(
            standing_b.match_points,
            2,
        )
