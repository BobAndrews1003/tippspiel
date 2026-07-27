from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tipping.models import (
    BonusPrediction,
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    Prediction,
    Tournament,
)
from tipping.result_processing import (
    process_match_change,
)


class BonusStandingIntegrationTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="bonus-integration-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Bonus-Integration-Turnier",
            season_start=(
                timezone.now()
                - timedelta(days=5)
            ),
            champion="Equipo A",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Bonus-Integration-Gruppe",
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
            pred_home=2,
            pred_away=1,
        )

        BonusPrediction.objects.create(
            user=self.user,
            group=self.group,
            bonus_type="meister",
            value="Equipo A",
        )

    def set_result_without_signal(self):
        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        self.match.refresh_from_db()

    def test_full_rebuild_includes_bonus_points(self):
        self.set_result_without_signal()

        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

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

    def test_management_command_includes_bonus_points(
        self,
    ):
        self.set_result_without_signal()

        # Zuerst die Prediction-Punkte berechnen.
        process_match_change(
            match_id=self.match.id,
            previous_matchday=1,
        )

        # Falsche vorberechnete Werte simulieren.
        GroupStanding.objects.filter(
            group=self.group,
            user=self.user,
        ).update(
            match_points=0,
            bonus_points=0,
            total_points=0,
        )

        call_command(
            "rebuild_standings",
            group_id=self.group.id,
            stdout=StringIO(),
        )

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
