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


class MatchDeleteProcessingTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="match-delete-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Match-Delete-Turnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Match-Delete-Gruppe",
            owner=self.user,
        )

        GroupMembership.objects.create(
            group=self.group,
            user=self.user,
            is_creator=True,
        )

    def create_finished_match(
        self,
        *,
        matchday,
        home_team,
        away_team,
        pred_home=2,
        pred_away=1,
        home_score=2,
        away_score=1,
    ):
        match = Match.objects.create(
            tournament=self.tournament,
            home_team=home_team,
            away_team=away_team,
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
            matchday=matchday,
        )

        Prediction.objects.create(
            group=self.group,
            user=self.user,
            match=match,
            pred_home=pred_home,
            pred_away=pred_away,
        )

        # Ergebnis setzen, ohne das Signal auszuführen.
        Match.objects.filter(
            pk=match.pk,
        ).update(
            home_score=home_score,
            away_score=away_score,
        )

        match.refresh_from_db()

        process_match_change(
            match_id=match.id,
            previous_matchday=matchday,
        )

        return match

    def test_delete_last_result_removes_matchday_score(
        self,
    ):
        match = self.create_finished_match(
            matchday=1,
            home_team="Equipo A",
            away_team="Equipo B",
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            4,
        )

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            match.delete()

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group,
                matchday=1,
            ).exists()
        )

        standing.refresh_from_db()

        self.assertEqual(
            standing.match_points,
            0,
        )

        self.assertEqual(
            standing.total_points,
            standing.bonus_points,
        )

    def test_delete_one_match_recalculates_remaining_points(
        self,
    ):
        first_match = self.create_finished_match(
            matchday=1,
            home_team="Equipo A",
            away_team="Equipo B",
        )

        self.create_finished_match(
            matchday=1,
            home_team="Equipo C",
            away_team="Equipo D",
        )

        score = MatchdayScore.objects.get(
            group=self.group,
            user=self.user,
            matchday=1,
        )

        self.assertEqual(
            score.points,
            8,
        )

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            first_match.delete()

        score.refresh_from_db()

        self.assertEqual(
            score.points,
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

    def test_delete_earlier_match_updates_later_cumulative_points(
        self,
    ):
        first_match = self.create_finished_match(
            matchday=1,
            home_team="Equipo A",
            away_team="Equipo B",
        )

        self.create_finished_match(
            matchday=2,
            home_team="Equipo C",
            away_team="Equipo D",
        )

        score_day_2 = MatchdayScore.objects.get(
            group=self.group,
            user=self.user,
            matchday=2,
        )

        self.assertEqual(
            score_day_2.cumulative_points,
            8,
        )

        # Das Löschen eines historischen Spiels wird nicht
        # mehr im Web-Request vollständig verarbeitet.
        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            first_match.delete()

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

        # Vor dem Worker ist das Read Model bewusst noch
        # auf dem zuletzt vollständig verarbeiteten Stand.
        score_day_2.refresh_from_db()

        self.assertEqual(
            score_day_2.cumulative_points,
            8,
        )

        call_command(
            "process_standing_jobs",
            limit=10,
            stdout=StringIO(),
            stderr=StringIO(),
        )

        job.refresh_from_db()

        self.assertEqual(
            job.status,
            StandingRebuildJob.Status.COMPLETED,
        )

        score_day_2.refresh_from_db()

        self.assertEqual(
            score_day_2.points,
            4,
        )

        self.assertEqual(
            score_day_2.cumulative_points,
            4,
        )

        self.assertEqual(
            score_day_2.rank,
            1,
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            4,
        )
