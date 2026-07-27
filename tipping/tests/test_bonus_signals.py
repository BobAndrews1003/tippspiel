from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tipping.models import (
    BonusPrediction,
    Group,
    GroupMembership,
    GroupStanding,
    MatchdayScore,
    Tournament,
)
from tipping.standings import (
    rebuild_group_bonus_points,
)


class BonusSignalTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="bonus-signal-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Bonus-Signal-Turnier",
            season_start=(
                timezone.now()
                + timedelta(days=5)
            ),
            champion="Equipo A",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Bonus-Signal-Gruppe",
            owner=self.user,
        )

        GroupMembership.objects.create(
            user=self.user,
            group=self.group,
            is_creator=True,
        )

        MatchdayScore.objects.create(
            group=self.group,
            user=self.user,
            matchday=1,
            points=7,
        )

        self.prediction = (
            BonusPrediction.objects.create(
                user=self.user,
                group=self.group,
                bonus_type="meister",
                value="Equipo A",
            )
        )

        rebuild_group_bonus_points(
            group_id=self.group.id,
        )

    def test_prediction_update_rebuilds_bonus_points(
        self,
    ):
        self.prediction.value = "Equipo X"

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.prediction.save(
                update_fields=[
                    "value",
                ],
            )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.match_points,
            7,
        )

        self.assertEqual(
            standing.bonus_points,
            0,
        )

        self.assertEqual(
            standing.total_points,
            7,
        )

    def test_prediction_delete_rebuilds_bonus_points(
        self,
    ):
        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.prediction.delete()

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.bonus_points,
            0,
        )

        self.assertEqual(
            standing.total_points,
            7,
        )

    def test_official_result_update_rebuilds_group(
        self,
    ):
        self.tournament.champion = "Equipo X"

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.tournament.save(
                update_fields=[
                    "champion",
                ],
            )

        standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        self.assertEqual(
            standing.bonus_points,
            0,
        )

        self.assertEqual(
            standing.total_points,
            7,
        )

    def test_tournament_update_rebuilds_all_groups(
        self,
    ):
        User = get_user_model()

        second_user = User.objects.create_user(
            username="bonus-signal-second",
            password="test-password-123",
        )

        second_group = Group.objects.create(
            tournament=self.tournament,
            name="Zweite Bonus-Gruppe",
            owner=second_user,
        )

        GroupMembership.objects.create(
            user=second_user,
            group=second_group,
            is_creator=True,
        )

        MatchdayScore.objects.create(
            group=second_group,
            user=second_user,
            matchday=1,
            points=3,
        )

        BonusPrediction.objects.create(
            user=second_user,
            group=second_group,
            bonus_type="meister",
            value="Equipo A",
        )

        rebuild_group_bonus_points(
            group_id=second_group.id,
        )

        self.tournament.champion = "Equipo X"

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.tournament.save(
                update_fields=[
                    "champion",
                ],
            )

        first_standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )

        second_standing = GroupStanding.objects.get(
            group=second_group,
            user=second_user,
        )

        self.assertEqual(
            first_standing.bonus_points,
            0,
        )

        self.assertEqual(
            second_standing.bonus_points,
            0,
        )

        self.assertEqual(
            first_standing.total_points,
            7,
        )

        self.assertEqual(
            second_standing.total_points,
            3,
        )
