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
from tipping.standing_jobs import (
    enqueue_standing_rebuild,
)


class StandingRebuildJobTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="standing-job-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Standing-Job-Turnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Standing-Job-Gruppe",
            owner=self.user,
        )

        GroupMembership.objects.create(
            group=self.group,
            user=self.user,
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
            group=self.group,
            user=self.user,
            match=self.match,
            pred_home=2,
            pred_away=1,
        )

        # Ergebnis ohne Signal und automatischen Rebuild.
        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        self.match.refresh_from_db()

    def test_pending_jobs_of_same_tournament_are_merged(
        self,
    ):
        first_job = enqueue_standing_rebuild(
            tournament_id=self.tournament.id,
            affected_matchdays=[
                3,
                5,
            ],
            match_ids=[
                20,
            ],
        )

        second_job = enqueue_standing_rebuild(
            tournament_id=self.tournament.id,
            affected_matchdays=[
                1,
                3,
            ],
            match_ids=[
                10,
                20,
            ],
            rebuild_bonus=True,
        )

        self.assertEqual(
            first_job.id,
            second_job.id,
        )

        self.assertEqual(
            StandingRebuildJob.objects.count(),
            1,
        )

        second_job.refresh_from_db()

        self.assertEqual(
            second_job.affected_matchdays,
            [
                1,
                3,
                5,
            ],
        )

        self.assertEqual(
            second_job.match_ids,
            [
                10,
                20,
            ],
        )

        self.assertTrue(
            second_job.rebuild_bonus
        )

    def test_worker_processes_pending_job(
        self,
    ):
        job = enqueue_standing_rebuild(
            tournament_id=self.tournament.id,
            affected_matchdays=[
                1,
            ],
            match_ids=[
                self.match.id,
            ],
        )

        output = StringIO()

        call_command(
            "process_standing_jobs",
            limit=10,
            stdout=output,
            stderr=StringIO(),
        )

        job.refresh_from_db()
        self.prediction.refresh_from_db()

        self.assertEqual(
            job.status,
            StandingRebuildJob.Status.COMPLETED,
        )

        self.assertEqual(
            job.attempts,
            1,
        )

        self.assertEqual(
            job.processed_groups,
            1,
        )

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

        self.assertEqual(
            score.points,
            4,
        )

        self.assertEqual(
            standing.match_points,
            4,
        )

        self.assertIn(
            "abgeschlossen",
            output.getvalue(),
        )

    def test_invalid_job_is_marked_failed(
        self,
    ):
        job = StandingRebuildJob.objects.create(
            tournament=self.tournament,
            affected_matchdays=[
                0,
            ],
            match_ids=[],
        )

        error_output = StringIO()

        call_command(
            "process_standing_jobs",
            limit=10,
            stdout=StringIO(),
            stderr=error_output,
        )

        job.refresh_from_db()

        self.assertEqual(
            job.status,
            StandingRebuildJob.Status.FAILED,
        )

        self.assertEqual(
            job.attempts,
            1,
        )

        self.assertTrue(
            job.last_error
        )

        self.assertIn(
            "fehlgeschlagen",
            error_output.getvalue(),
        )
