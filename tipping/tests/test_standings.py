from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
)
from tipping.standings import rebuild_matchday_scores


class RebuildMatchdayScoresTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.creator = User.objects.create_user(
            username="creator",
            password="test-password-123",
        )

        self.second_user = User.objects.create_user(
            username="second-user",
            password="test-password-123",
        )

        self.user_without_tips = User.objects.create_user(
            username="without-tips",
            password="test-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Testturnier",
        )

        self.group_a = Group.objects.create(
            tournament=self.tournament,
            name="Gruppe A",
            owner=self.creator,
        )

        self.group_b = Group.objects.create(
            tournament=self.tournament,
            name="Gruppe B",
            owner=self.creator,
        )

        GroupMembership.objects.create(
            user=self.creator,
            group=self.group_a,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.second_user,
            group=self.group_a,
        )

        GroupMembership.objects.create(
            user=self.user_without_tips,
            group=self.group_a,
        )

        GroupMembership.objects.create(
            user=self.creator,
            group=self.group_b,
            is_creator=True,
        )

        kickoff = (
            timezone.now()
            - timedelta(days=1)
        )

        self.match_1 = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=kickoff,
            matchday=1,
            home_score=2,
            away_score=1,
        )

        self.match_2 = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=kickoff,
            matchday=1,
            home_score=1,
            away_score=1,
        )

        # Gruppe A:
        # creator = 4 + 2 = 6 Punkte
        # second_user = 3 Punkte
        # user_without_tips = 0 Punkte

        self.creator_prediction_1 = (
            Prediction.objects.create(
                user=self.creator,
                group=self.group_a,
                match=self.match_1,
                pred_home=2,
                pred_away=1,
                points=4,
            )
        )

        self.creator_prediction_2 = (
            Prediction.objects.create(
                user=self.creator,
                group=self.group_a,
                match=self.match_2,
                pred_home=0,
                pred_away=0,
                points=2,
            )
        )

        Prediction.objects.create(
            user=self.second_user,
            group=self.group_a,
            match=self.match_1,
            pred_home=3,
            pred_away=2,
            points=3,
        )

        # Derselbe Nutzer tippt dasselbe Spiel
        # in Gruppe B anders.
        Prediction.objects.create(
            user=self.creator,
            group=self.group_b,
            match=self.match_1,
            pred_home=1,
            pred_away=0,
            points=2,
        )

    def test_rebuild_creates_correct_scores_for_all_members(
        self,
    ):
        count = rebuild_matchday_scores(
            group_id=self.group_a.id,
            matchday=1,
        )

        self.assertEqual(count, 3)

        creator_score = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.creator,
            matchday=1,
        )

        second_user_score = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.second_user,
            matchday=1,
        )

        no_tip_score = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.user_without_tips,
            matchday=1,
        )

        self.assertEqual(
            creator_score.points,
            6,
        )

        self.assertEqual(
            creator_score.exact_predictions,
            1,
        )

        self.assertEqual(
            second_user_score.points,
            3,
        )

        self.assertEqual(
            second_user_score.exact_predictions,
            0,
        )

        self.assertEqual(
            no_tip_score.points,
            0,
        )

        self.assertEqual(
            no_tip_score.exact_predictions,
            0,
        )

    def test_groups_are_strictly_separated(self):
        rebuild_matchday_scores(
            group_id=self.group_a.id,
            matchday=1,
        )

        group_a_score = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.creator,
            matchday=1,
        )

        self.assertEqual(
            group_a_score.points,
            6,
        )

        # Der Rebuild von Gruppe A darf keine Zeilen
        # für Gruppe B erzeugen.
        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group_b,
            ).exists()
        )

        rebuild_matchday_scores(
            group_id=self.group_b.id,
            matchday=1,
        )

        group_b_score = MatchdayScore.objects.get(
            group=self.group_b,
            user=self.creator,
            matchday=1,
        )

        self.assertEqual(
            group_b_score.points,
            2,
        )

        # Der Punktestand in Gruppe A bleibt unverändert.
        group_a_score.refresh_from_db()

        self.assertEqual(
            group_a_score.points,
            6,
        )

    def test_rebuild_is_idempotent(self):
        first_count = rebuild_matchday_scores(
            group_id=self.group_a.id,
            matchday=1,
        )

        second_count = rebuild_matchday_scores(
            group_id=self.group_a.id,
            matchday=1,
        )

        self.assertEqual(first_count, 3)
        self.assertEqual(second_count, 3)

        self.assertEqual(
            MatchdayScore.objects.filter(
                group=self.group_a,
                matchday=1,
            ).count(),
            3,
        )

    def test_rebuild_updates_existing_rows(self):
        rebuild_matchday_scores(
            group_id=self.group_a.id,
            matchday=1,
        )

        score = MatchdayScore.objects.get(
            group=self.group_a,
            user=self.creator,
            matchday=1,
        )

        self.assertEqual(
            score.points,
            6,
        )

        self.assertEqual(
            score.exact_predictions,
            1,
        )

        # Zweiter Tipp wird nachträglich von
        # 2 auf 4 Punkte korrigiert.
        self.creator_prediction_2.points = 4
        self.creator_prediction_2.save(
            update_fields=[
                "points",
            ],
        )

        rebuild_matchday_scores(
            group_id=self.group_a.id,
            matchday=1,
        )

        score.refresh_from_db()

        self.assertEqual(
            score.points,
            8,
        )

        self.assertEqual(
            score.exact_predictions,
            2,
        )

    def test_departed_members_are_removed(self):
        rebuild_matchday_scores(
            group_id=self.group_a.id,
            matchday=1,
        )

        self.assertTrue(
            MatchdayScore.objects.filter(
                group=self.group_a,
                user=self.user_without_tips,
                matchday=1,
            ).exists()
        )

        GroupMembership.objects.filter(
            group=self.group_a,
            user=self.user_without_tips,
        ).delete()

        rebuild_matchday_scores(
            group_id=self.group_a.id,
            matchday=1,
        )

        self.assertFalse(
            MatchdayScore.objects.filter(
                group=self.group_a,
                user=self.user_without_tips,
                matchday=1,
            ).exists()
        )

    def test_invalid_matchday_is_rejected(self):
        with self.assertRaises(ValueError):
            rebuild_matchday_scores(
                group_id=self.group_a.id,
                matchday=0,
            )
