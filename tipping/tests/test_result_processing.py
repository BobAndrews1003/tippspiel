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
from tipping.result_processing import (
    process_match_change,
)


class ProcessMatchChangeTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user_a = User.objects.create_user(
            username="processing-a",
            password="test-password-123",
        )

        self.user_b = User.objects.create_user(
            username="processing-b",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Processing-Testturnier",
        )

        self.group_a = Group.objects.create(
            tournament=self.tournament,
            name="Processing Gruppe A",
            owner=self.user_a,
        )

        self.group_b = Group.objects.create(
            tournament=self.tournament,
            name="Processing Gruppe B",
            owner=self.user_b,
        )

        GroupMembership.objects.create(
            user=self.user_a,
            group=self.group_a,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.user_b,
            group=self.group_b,
            is_creator=True,
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

        self.prediction = Prediction.objects.create(
            user=self.user_a,
            group=self.group_a,
            match=self.match,
            pred_home=2,
            pred_away=1,
        )

    def set_result_without_signal(
        self,
        home_score,
        away_score,
    ):
        """
        QuerySet.update() wird absichtlich verwendet,
        damit nur process_match_change getestet wird.
        """

        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            home_score=home_score,
            away_score=away_score,
        )

        self.match.refresh_from_db()

    def test_new_result_updates_all_derived_tables(
        self,
    ):
        self.set_result_without_signal(
            2,
            1,
        )

        processed_groups = process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        self.assertEqual(
            processed_groups,
            2,
        )

        self.prediction.refresh_from_db()

        self.assertEqual(
            self.prediction.points,
            4,
        )

        score_a = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.user_a,
            matchday=1,
        )

        standing_a = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user_a,
        )

        self.assertEqual(score_a.points, 4)
        self.assertEqual(
            score_a.cumulative_points,
            4,
        )
        self.assertEqual(score_a.rank, 1)

        self.assertEqual(
            standing_a.match_points,
            4,
        )
        self.assertEqual(
            standing_a.total_points,
            4,
        )

    def test_group_without_prediction_gets_zero_score(
        self,
    ):
        self.set_result_without_signal(
            2,
            1,
        )

        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        score_b = MatchdayScore.objects.get(
            group=self.group_b,
            user=self.user_b,
            matchday=1,
        )

        standing_b = GroupStanding.objects.get(
            group=self.group_b,
            user=self.user_b,
        )

        self.assertEqual(score_b.points, 0)
        self.assertEqual(
            score_b.cumulative_points,
            0,
        )
        self.assertEqual(score_b.rank, 1)

        self.assertEqual(
            standing_b.match_points,
            0,
        )
        self.assertEqual(
            standing_b.total_points,
            0,
        )

    def test_result_correction_updates_scores(
        self,
    ):
        self.set_result_without_signal(
            2,
            1,
        )

        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        self.set_result_without_signal(
            1,
            1,
        )

        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        self.prediction.refresh_from_db()

        self.assertEqual(
            self.prediction.points,
            0,
        )

        score = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.user_a,
            matchday=1,
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user_a,
        )

        self.assertEqual(score.points, 0)
        self.assertEqual(
            score.cumulative_points,
            0,
        )
        self.assertEqual(
            standing.match_points,
            0,
        )

    def test_removed_result_clears_scores(
        self,
    ):
        self.set_result_without_signal(
            2,
            1,
        )

        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        self.set_result_without_signal(
            None,
            None,
        )

        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        self.prediction.refresh_from_db()

        self.assertIsNone(
            self.prediction.points,
        )

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group_a,
                matchday=1,
            ).exists()
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user_a,
        )

        self.assertEqual(
            standing.match_points,
            0,
        )

        self.assertEqual(
            standing.total_points,
            0,
        )

    def test_matchday_change_rebuilds_old_and_new_day(
        self,
    ):
        self.set_result_without_signal(
            2,
            1,
        )

        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            matchday=2,
        )

        self.match.refresh_from_db()

        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group_a,
                matchday=1,
            ).exists()
        )

        score = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.user_a,
            matchday=2,
        )

        self.assertEqual(score.points, 4)
        self.assertEqual(
            score.cumulative_points,
            4,
        )
        self.assertEqual(score.rank, 1)


class MatchSignalIntegrationTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="signal-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Signal-Testturnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Signal Gruppe",
            owner=self.user,
        )

        GroupMembership.objects.create(
            user=self.user,
            group=self.group,
            is_creator=True,
        )

        self.match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
            matchday=1,
        )

        self.prediction = Prediction.objects.create(
            user=self.user,
            group=self.group,
            match=self.match,
            pred_home=1,
            pred_away=0,
        )

    def test_signal_processes_result_after_commit(
        self,
    ):
        self.match.home_score = 1
        self.match.away_score = 0

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.match.save(
                update_fields=[
                    "home_score",
                    "away_score",
                ],
            )

        self.prediction.refresh_from_db()

        self.assertEqual(
            self.prediction.points,
            4,
        )

        score = MatchdayScore.objects.get(
            group=self.group,
            user=self.user,
            matchday=1,
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(score.points, 4)
        self.assertEqual(score.rank, 1)

        self.assertEqual(
            standing.match_points,
            4,
        )
