from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tipping.bonus_scoring import (
    bonus_points_for_user,
    get_bonus_lock_time,
)
from tipping.models import (
    BonusPrediction,
    Group,
    GroupMembership,
    Match,
    Tournament,
)


class BonusScoringTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="bonus-user",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Bonus-Testturnier",
            autumn_champion="Equipo A",
            champion="Equipo B",
            first_coach_sacked="Entrenador C",
            top_scorer="Jugador D",
            relegated_teams="Equipo E, Equipo F",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Bonus-Testgruppe",
            owner=self.user,
        )

        GroupMembership.objects.create(
            user=self.user,
            group=self.group,
            is_creator=True,
        )

    def create_prediction(
        self,
        bonus_type,
        value,
    ):
        return BonusPrediction.objects.create(
            user=self.user,
            group=self.group,
            bonus_type=bonus_type,
            value=value,
        )

    def test_all_correct_predictions_give_thirty_points(
        self,
    ):
        predictions = [
            self.create_prediction(
                "herbstmeister",
                "Equipo A",
            ),
            self.create_prediction(
                "meister",
                "Equipo B",
            ),
            self.create_prediction(
                "trainer_first",
                "Entrenador C",
            ),
            self.create_prediction(
                "topscorer",
                "Jugador D",
            ),
            self.create_prediction(
                "relegation1",
                "Equipo E",
            ),
            self.create_prediction(
                "relegation2",
                "Equipo F",
            ),
        ]

        self.assertEqual(
            bonus_points_for_user(
                self.tournament,
                predictions,
            ),
            30,
        )

    def test_wrong_predictions_give_zero_points(
        self,
    ):
        predictions = [
            self.create_prediction(
                "meister",
                "Equipo X",
            ),
            self.create_prediction(
                "topscorer",
                "Jugador X",
            ),
        ]

        self.assertEqual(
            bonus_points_for_user(
                self.tournament,
                predictions,
            ),
            0,
        )

    def test_comparison_ignores_case_and_whitespace(
        self,
    ):
        predictions = [
            self.create_prediction(
                "meister",
                "  EQUIPO B  ",
            ),
            self.create_prediction(
                "topscorer",
                " jugador d ",
            ),
        ]

        self.assertEqual(
            bonus_points_for_user(
                self.tournament,
                predictions,
            ),
            10,
        )

    def test_duplicate_relegation_is_not_counted_twice(
        self,
    ):
        predictions = [
            self.create_prediction(
                "relegation1",
                "Equipo E",
            ),
            self.create_prediction(
                "relegation2",
                "Equipo E",
            ),
        ]

        self.assertEqual(
            bonus_points_for_user(
                self.tournament,
                predictions,
            ),
            5,
        )

    def test_missing_official_result_gives_no_points(
        self,
    ):
        self.tournament.champion = ""
        self.tournament.save(
            update_fields=[
                "champion",
            ],
        )

        predictions = [
            self.create_prediction(
                "meister",
                "Equipo B",
            ),
        ]

        self.assertEqual(
            bonus_points_for_user(
                self.tournament,
                predictions,
            ),
            0,
        )


class BonusLockTimeTests(TestCase):
    def setUp(self):
        self.season_start = (
            timezone.now()
            + timedelta(days=10)
        )

        self.tournament = Tournament.objects.create(
            name="Lock-Testturnier",
            season_start=self.season_start,
        )

    def test_season_start_is_fallback_without_matches(
        self,
    ):
        self.assertEqual(
            get_bonus_lock_time(
                self.tournament,
            ),
            self.season_start,
        )

    def test_first_match_kickoff_has_priority(
        self,
    ):
        later_kickoff = (
            timezone.now()
            + timedelta(days=5)
        )

        first_kickoff = (
            timezone.now()
            + timedelta(days=2)
        )

        Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=later_kickoff,
            matchday=1,
        )

        Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=first_kickoff,
            matchday=1,
        )

        self.assertEqual(
            get_bonus_lock_time(
                self.tournament,
            ),
            first_kickoff,
        )
