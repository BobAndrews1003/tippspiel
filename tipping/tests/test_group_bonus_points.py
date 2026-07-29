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


class RebuildGroupBonusPointsTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user_a = User.objects.create_user(
            username="bonus-standing-a",
            password="test-password-123",
        )

        self.user_b = User.objects.create_user(
            username="bonus-standing-b",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Bonus-Standing-Turnier",
            season_start=(
                timezone.now()
                - timedelta(days=1)
            ),
            champion="Equipo A",
            top_scorer="Jugador B",
        )

        self.group_a = Group.objects.create(
            tournament=self.tournament,
            name="Bonus Standing Gruppe A",
            owner=self.user_a,
        )

        self.group_b = Group.objects.create(
            tournament=self.tournament,
            name="Bonus Standing Gruppe B",
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

        MatchdayScore.objects.create(
            group=self.group_a,
            user=self.user_a,
            matchday=1,
            points=7,
            exact_predictions=1,
        )

        MatchdayScore.objects.create(
            group=self.group_b,
            user=self.user_b,
            matchday=1,
            points=3,
        )

        BonusPrediction.objects.create(
            user=self.user_a,
            group=self.group_a,
            bonus_type="meister",
            value="Equipo A",
        )

        BonusPrediction.objects.create(
            user=self.user_a,
            group=self.group_a,
            bonus_type="topscorer",
            value="Jugador B",
        )

        BonusPrediction.objects.create(
            user=self.user_b,
            group=self.group_b,
            bonus_type="meister",
            value="Equipo X",
        )

    def test_correct_bonus_points_are_stored(self):
        count = rebuild_group_bonus_points(
            group_id=self.group_a.id,
        )

        self.assertEqual(count, 1)

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user_a,
        )

        self.assertEqual(
            standing.match_points,
            7,
        )

        self.assertEqual(
            standing.bonus_points,
            10,
        )

        self.assertEqual(
            standing.total_points,
            17,
        )

    def test_groups_are_strictly_separated(self):
        rebuild_group_bonus_points(
            group_id=self.group_a.id,
        )

        self.assertFalse(
            GroupStanding.objects.filter(
                group=self.group_b,
            ).exists()
        )

        rebuild_group_bonus_points(
            group_id=self.group_b.id,
        )

        standing_a = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user_a,
        )

        standing_b = GroupStanding.objects.get(
            group=self.group_b,
            user=self.user_b,
        )

        self.assertEqual(
            standing_a.bonus_points,
            10,
        )

        self.assertEqual(
            standing_b.bonus_points,
            0,
        )

        self.assertEqual(
            standing_b.total_points,
            3,
        )

    def test_bonus_points_are_precomputed_before_reveal(
            self,
            ):
        self.tournament.season_start = (
            timezone.now()
            + timedelta(days=2)
        )

        self.tournament.save(
            update_fields=[
                "season_start",
            ],
        )

        rebuild_group_bonus_points(
            group_id=self.group_a.id,
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user_a,
        )

        # Die Punkte sind intern bereits vorbereitet.
        # Die View darf sie vor der Freigabe noch nicht
        # anzeigen oder für die sichtbare Tabelle verwenden.
        self.assertEqual(
            standing.bonus_points,
            10,
        )

        self.assertEqual(
            standing.total_points,
            17,
        )

    def test_rebuild_updates_changed_official_result(
        self,
    ):
        rebuild_group_bonus_points(
            group_id=self.group_a.id,
        )

        self.tournament.champion = "Equipo X"
        self.tournament.save(
            update_fields=[
                "champion",
            ],
        )

        rebuild_group_bonus_points(
            group_id=self.group_a.id,
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user_a,
        )

        self.assertEqual(
            standing.bonus_points,
            5,
        )

        self.assertEqual(
            standing.total_points,
            12,
        )

    def test_rebuild_is_idempotent(self):
        first_count = rebuild_group_bonus_points(
            group_id=self.group_a.id,
        )

        second_count = rebuild_group_bonus_points(
            group_id=self.group_a.id,
        )

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)

        self.assertEqual(
            GroupStanding.objects.filter(
                group=self.group_a,
                user=self.user_a,
            ).count(),
            1,
        )

        standing = GroupStanding.objects.get(
            group=self.group_a,
            user=self.user_a,
        )

        self.assertEqual(
            standing.total_points,
            17,
        )
