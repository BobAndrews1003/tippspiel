from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    Match,
    MatchdayScore,
    Prediction,
    StandingRebuildJob,
    Tournament,
)
from tipping.result_processing import (
    process_match_change,
)


class MatchTournamentChangeTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="tournament-change-user",
            password="test-password-123",
        )

        self.tournament_a = (
            Tournament.objects.create(
                name="Turnier A",
            )
        )

        self.tournament_b = (
            Tournament.objects.create(
                name="Turnier B",
            )
        )

        self.group_a = Group.objects.create(
            tournament=self.tournament_a,
            name="Gruppe A",
            owner=self.user,
        )

        self.group_b = Group.objects.create(
            tournament=self.tournament_b,
            name="Gruppe B",
            owner=self.user,
        )

        GroupMembership.objects.create(
            group=self.group_a,
            user=self.user,
            is_creator=True,
        )

        GroupMembership.objects.create(
            group=self.group_b,
            user=self.user,
            is_creator=True,
        )

    def create_finished_match(
        self,
        *,
        tournament,
        matchday,
        name,
    ):
        match = Match.objects.create(
            tournament=tournament,
            home_team=f"{name} Local",
            away_team=f"{name} Visitante",
            kickoff=(
                timezone.now()
                - timedelta(days=matchday + 1)
            ),
            matchday=matchday,
        )

        Match.objects.filter(
            pk=match.id,
        ).update(
            home_score=2,
            away_score=1,
        )

        match.refresh_from_db()

        process_match_change(
            match_id=match.id,
            previous_matchday=matchday,
            rebuild_bonus=False,
        )

        return match

    def run_worker(self):
        call_command(
            "process_standing_jobs",
            limit=10,
            stdout=StringIO(),
            stderr=StringIO(),
        )

    def test_tournament_change_with_predictions_is_rejected(
        self,
    ):
        match = Match.objects.create(
            tournament=self.tournament_a,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                + timedelta(days=1)
            ),
            matchday=1,
        )

        Prediction.objects.create(
            group=self.group_a,
            user=self.user,
            match=match,
            pred_home=2,
            pred_away=1,
        )

        match.tournament = self.tournament_b

        with self.assertRaises(
            ValidationError,
        ):
            match.save(
                update_fields=[
                    "tournament",
                ]
            )

        match.refresh_from_db()

        self.assertEqual(
            match.tournament_id,
            self.tournament_a.id,
        )

    def test_finished_match_without_predictions_moves_read_model(
        self,
    ):
        match = self.create_finished_match(
            tournament=self.tournament_a,
            matchday=1,
            name="Primero",
        )

        self.assertTrue(
            MatchdayScore.objects.filter(
                group=self.group_a,
                matchday=1,
            ).exists()
        )

        match.tournament = self.tournament_b

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            match.save(
                update_fields=[
                    "tournament",
                ]
            )

        self.assertFalse(
            StandingRebuildJob.objects.exists()
        )

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group_a,
                matchday=1,
            ).exists()
        )

        new_score = MatchdayScore.objects.get(
            group=self.group_b,
            user=self.user,
            matchday=1,
        )

        self.assertEqual(
            new_score.points,
            0,
        )

        self.assertEqual(
            new_score.cumulative_points,
            0,
        )

    def test_historical_tournament_change_queues_both_tournaments(
        self,
    ):
        match = self.create_finished_match(
            tournament=self.tournament_a,
            matchday=1,
            name="Historico",
        )

        self.create_finished_match(
            tournament=self.tournament_a,
            matchday=2,
            name="Posterior A",
        )

        self.create_finished_match(
            tournament=self.tournament_b,
            matchday=2,
            name="Posterior B",
        )

        match.tournament = self.tournament_b

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            match.save(
                update_fields=[
                    "tournament",
                ]
            )

        jobs = list(
            StandingRebuildJob.objects
            .order_by("tournament_id")
        )

        self.assertEqual(
            len(jobs),
            2,
        )

        self.assertEqual(
            {
                job.tournament_id
                for job in jobs
            },
            {
                self.tournament_a.id,
                self.tournament_b.id,
            },
        )

        self.assertTrue(
            all(
                job.affected_matchdays == [1]
                for job in jobs
            )
        )

        self.run_worker()

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group_a,
                matchday=1,
            ).exists()
        )

        self.assertTrue(
            MatchdayScore.objects.filter(
                group=self.group_b,
                matchday=1,
            ).exists()
        )

        self.assertFalse(
            StandingRebuildJob.objects.exclude(
                status=(
                    StandingRebuildJob
                    .Status
                    .COMPLETED
                ),
            ).exists()
        )
