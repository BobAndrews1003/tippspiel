from datetime import timedelta
from unittest.mock import patch

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


class PredictionSignalTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="prediction-signal-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Prediction-Signal-Turnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Prediction-Signal-Gruppe",
            owner=self.user,
        )

        GroupMembership.objects.create(
            group=self.group,
            user=self.user,
            is_creator=True,
        )

        self.finished_match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
            matchday=1,
        )

        # Ergebnis ohne Match-Signal setzen.
        Match.objects.filter(
            pk=self.finished_match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        self.finished_match.refresh_from_db()

    def create_processed_prediction(
        self,
    ):
        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            prediction = Prediction.objects.create(
                group=self.group,
                user=self.user,
                match=self.finished_match,
                pred_home=2,
                pred_away=1,
            )

        prediction.refresh_from_db()

        return prediction

    def test_late_prediction_create_updates_read_model(
        self,
    ):
        prediction = (
            self.create_processed_prediction()
        )

        self.assertEqual(
            prediction.points,
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
        self.assertEqual(
            score.exact_predictions,
            1,
        )

        self.assertEqual(
            standing.match_points,
            4,
        )

        self.assertEqual(
            standing.exact_predictions,
            1,
        )

    def test_prediction_correction_updates_points(
        self,
    ):
        prediction = (
            self.create_processed_prediction()
        )

        prediction.pred_home = 0
        prediction.pred_away = 1

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            prediction.save(
                update_fields=[
                    "pred_home",
                    "pred_away",
                ],
            )

        prediction.refresh_from_db()

        self.assertEqual(
            prediction.points,
            0,
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

        self.assertEqual(score.points, 0)

        self.assertEqual(
            standing.match_points,
            0,
        )

    def test_prediction_delete_updates_read_model(
        self,
    ):
        prediction = (
            self.create_processed_prediction()
        )

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            prediction.delete()

        score = MatchdayScore.objects.get(
            group=self.group,
            user=self.user,
            matchday=1,
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(score.points, 0)

        self.assertEqual(
            standing.match_points,
            0,
        )

        self.assertEqual(
            standing.exact_predictions,
            0,
        )

    def test_unfinished_match_does_not_create_score(
        self,
    ):
        unfinished_match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=(
                timezone.now()
                + timedelta(days=1)
            ),
            matchday=2,
        )

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            prediction = Prediction.objects.create(
                group=self.group,
                user=self.user,
                match=unfinished_match,
                pred_home=1,
                pred_away=0,
            )

        prediction.refresh_from_db()

        self.assertIsNone(
            prediction.points,
        )

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group,
                matchday=2,
            ).exists()
        )

    def test_match_delete_does_not_duplicate_prediction_processing(
        self,
    ):
        self.create_processed_prediction()

        with patch(
            "tipping.prediction_signals."
            "process_prediction_delete"
        ) as mocked_prediction_delete:
            with self.captureOnCommitCallbacks(
                execute=True,
            ):
                self.finished_match.delete()

        mocked_prediction_delete.assert_not_called()

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group,
                matchday=1,
            ).exists()
        )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            0,
        )
