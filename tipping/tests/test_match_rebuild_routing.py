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
    StandingRebuildJob,
    Tournament,
)
from tipping.result_processing import (
    process_match_change,
)


class MatchRebuildRoutingTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="match-routing-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Match-Routing-Turnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Match-Routing-Gruppe",
            owner=self.user,
        )

        GroupMembership.objects.create(
            group=self.group,
            user=self.user,
            is_creator=True,
        )

        self.match_1 = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                - timedelta(days=2)
            ),
            matchday=1,
        )

        self.match_2 = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
            matchday=2,
        )

        self.prediction_1 = Prediction.objects.create(
            group=self.group,
            user=self.user,
            match=self.match_1,
            pred_home=2,
            pred_away=1,
        )

        self.prediction_2 = Prediction.objects.create(
            group=self.group,
            user=self.user,
            match=self.match_2,
            pred_home=2,
            pred_away=1,
        )

        # Ergebnisse ohne Match-Signale setzen.
        Match.objects.filter(
            pk__in=[
                self.match_1.id,
                self.match_2.id,
            ],
        ).update(
            home_score=2,
            away_score=1,
        )

        self.match_1.refresh_from_db()
        self.match_2.refresh_from_db()

        # Konsistentes Read Model herstellen.
        process_match_change(
            match_id=self.match_1.id,
            previous_matchday=1,
            rebuild_bonus=False,
        )

        process_match_change(
            match_id=self.match_2.id,
            previous_matchday=2,
            rebuild_bonus=False,
        )

    def run_worker(self):
        call_command(
            "process_standing_jobs",
            limit=10,
            stdout=StringIO(),
            stderr=StringIO(),
        )

    def test_latest_matchday_change_is_processed_immediately(
        self,
    ):
        self.match_2.home_score = 1
        self.match_2.away_score = 1

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.match_2.save(
                update_fields=[
                    "home_score",
                    "away_score",
                ]
            )

        self.assertFalse(
            StandingRebuildJob.objects.exists()
        )

        self.prediction_2.refresh_from_db()

        self.assertEqual(
            self.prediction_2.points,
            0,
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            4,
        )

    def test_historical_match_change_is_queued(
        self,
    ):
        self.match_1.home_score = 1
        self.match_1.away_score = 1

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.match_1.save(
                update_fields=[
                    "home_score",
                    "away_score",
                ]
            )

        job = StandingRebuildJob.objects.get()

        self.assertEqual(
            job.status,
            StandingRebuildJob.Status.PENDING,
        )

        self.assertEqual(
            job.affected_matchdays,
            [
                1,
            ],
        )

        self.assertEqual(
            job.match_ids,
            [
                self.match_1.id,
            ],
        )

        # Vor dem Worker ist das Read Model noch unverändert.
        self.prediction_1.refresh_from_db()

        self.assertEqual(
            self.prediction_1.points,
            4,
        )

        self.run_worker()

        job.refresh_from_db()
        self.prediction_1.refresh_from_db()

        self.assertEqual(
            job.status,
            StandingRebuildJob.Status.COMPLETED,
        )

        self.assertEqual(
            self.prediction_1.points,
            0,
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            4,
        )

        score_day_2 = MatchdayScore.objects.get(
            group=self.group,
            user=self.user,
            matchday=2,
        )

        self.assertEqual(
            score_day_2.cumulative_points,
            4,
        )

    def test_historical_match_delete_is_queued(
        self,
    ):
        deleted_match_id = self.match_1.id

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.match_1.delete()

        job = StandingRebuildJob.objects.get()

        self.assertEqual(
            job.status,
            StandingRebuildJob.Status.PENDING,
        )

        self.assertEqual(
            job.affected_matchdays,
            [
                1,
            ],
        )

        self.assertEqual(
            job.match_ids,
            [],
        )

        self.assertTrue(
            MatchdayScore.objects.filter(
                group=self.group,
                matchday=1,
            ).exists()
        )

        self.run_worker()

        job.refresh_from_db()

        self.assertEqual(
            job.status,
            StandingRebuildJob.Status.COMPLETED,
        )

        self.assertFalse(
            Match.objects.filter(
                pk=deleted_match_id,
            ).exists()
        )

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group,
                matchday=1,
            ).exists()
        )

        score_day_2 = MatchdayScore.objects.get(
            group=self.group,
            user=self.user,
            matchday=2,
        )

        self.assertEqual(
            score_day_2.cumulative_points,
            4,
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            4,
        )
