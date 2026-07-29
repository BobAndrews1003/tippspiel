from django.test import TestCase

from tipping.models import Match, Prediction
from tipping.scoring import points_for_prediction


class PredictionScoringTests(TestCase):
    def test_exact_result_gives_four_points(self):
        match = Match(
            home_score=2,
            away_score=1,
        )

        prediction = Prediction(
            pred_home=2,
            pred_away=1,
        )

        self.assertEqual(
            points_for_prediction(
                match,
                prediction,
            ),
            4,
        )

    def test_correct_goal_difference_gives_three_points(self):
        match = Match(
            home_score=2,
            away_score=0,
        )

        prediction = Prediction(
            pred_home=3,
            pred_away=1,
        )

        self.assertEqual(
            points_for_prediction(
                match,
                prediction,
            ),
            3,
        )

    def test_correct_tendency_gives_two_points(self):
        match = Match(
            home_score=2,
            away_score=0,
        )

        prediction = Prediction(
            pred_home=1,
            pred_away=0,
        )

        self.assertEqual(
            points_for_prediction(
                match,
                prediction,
            ),
            2,
        )

    def test_wrong_prediction_gives_zero_points(self):
        match = Match(
            home_score=2,
            away_score=0,
        )

        prediction = Prediction(
            pred_home=0,
            pred_away=1,
        )

        self.assertEqual(
            points_for_prediction(
                match,
                prediction,
            ),
            0,
        )