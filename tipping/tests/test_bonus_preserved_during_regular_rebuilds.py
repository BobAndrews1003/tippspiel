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
    Prediction,
    Tournament,
)
from tipping.prediction_processing import (
    process_prediction_change,
)
from tipping.result_processing import (
    process_match_change,
)


class BonusPreservedDuringRegularRebuildTests(
    TestCase
):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="bonus-preserved-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Bonus-Preserved-Turnier",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Bonus-Preserved-Gruppe",
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

        # Ergebnis ohne Match-Signal setzen.
        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        self.match.refresh_from_db()

        self.prediction = Prediction.objects.create(
            group=self.group,
            user=self.user,
            match=self.match,
            pred_home=2,
            pred_away=1,
        )

        # Bereits vorberechnete Bonuspunkte simulieren.
        GroupStanding.objects.create(
            group=self.group,
            user=self.user,
            match_points=0,
            bonus_points=5,
            total_points=5,
            exact_predictions=0,
        )

    def test_match_processing_preserves_bonus_without_rescoring(
        self,
    ):
        with patch(
            "tipping.standings."
            "bonus_points_for_user"
        ) as mocked_bonus_scoring:
            process_match_change(
                match_id=self.match.id,
                previous_matchday=1,
                rebuild_bonus=False,
            )

        mocked_bonus_scoring.assert_not_called()

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            4,
        )

        self.assertEqual(
            standing.bonus_points,
            5,
        )

        self.assertEqual(
            standing.total_points,
            9,
        )

    def test_prediction_processing_preserves_bonus_without_rescoring(
        self,
    ):
        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
            rebuild_bonus=False,
        )

        Prediction.objects.filter(
            pk=self.prediction.pk,
        ).update(
            pred_home=0,
            pred_away=1,
        )

        with patch(
            "tipping.standings."
            "bonus_points_for_user"
        ) as mocked_bonus_scoring:
            process_prediction_change(
                prediction_id=(
                    self.prediction.id
                ),
            )

        mocked_bonus_scoring.assert_not_called()

        self.prediction.refresh_from_db()

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            self.prediction.points,
            0,
        )

        self.assertEqual(
            standing.match_points,
            0,
        )

        self.assertEqual(
            standing.bonus_points,
            5,
        )

        self.assertEqual(
            standing.total_points,
            5,
        )
