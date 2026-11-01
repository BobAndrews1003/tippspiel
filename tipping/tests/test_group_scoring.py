from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    GroupScoringSettings,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
)
from tipping.scoring import (
    points_for_prediction,
    recalculate_points_for_match,
)
from tipping.standings import (
    rebuild_group_standing,
    rebuild_matchday_scores,
)


class GroupScoringSettingsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="scoring-owner",
            password="test-password-123",
        )
        self.member = User.objects.create_user(
            username="scoring-member",
            password="test-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Liga de puntuación",
        )
        self.group = Group.objects.create(
            name="Grupo de puntuación",
            tournament=self.tournament,
            owner=self.owner,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            is_creator=True,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.member,
        )

    def enable_paid_plan(self, plan=Group.Plan.PLUS):
        self.group.plan = plan
        self.group.plan_expires_at = (
            timezone.now() + timedelta(days=30)
        )
        self.group.save(
            update_fields=[
                "plan",
                "plan_expires_at",
            ]
        )

    def scoring_payload(self, **overrides):
        payload = {
            "form_action": "scoring",
            "preset": "custom",
            "exact_points": "7",
            "goal_difference_points": "4",
            "tendency_points": "2",
            "incorrect_points": "0",
        }
        payload.update(overrides)
        return payload

    def test_new_group_receives_standard_scoring_settings(self):
        settings = self.group.scoring_settings

        self.assertEqual(
            (
                settings.exact_points,
                settings.goal_difference_points,
                settings.tendency_points,
                settings.incorrect_points,
            ),
            (4, 3, 2, 0),
        )
        self.assertFalse(settings.is_locked)

    def test_plus_owner_can_save_custom_scoring(self):
        self.enable_paid_plan()
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
            self.scoring_payload(),
        )

        self.assertRedirects(
            response,
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
        )
        self.group.scoring_settings.refresh_from_db()
        self.assertEqual(
            (
                self.group.scoring_settings.exact_points,
                self.group.scoring_settings.goal_difference_points,
                self.group.scoring_settings.tendency_points,
                self.group.scoring_settings.incorrect_points,
            ),
            (7, 4, 2, 0),
        )

    def test_club_owner_can_use_scoring_preset(self):
        self.enable_paid_plan(Group.Plan.CLUB)
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
            self.scoring_payload(
                preset="exact_focus",
                exact_points="1",
                goal_difference_points="1",
                tendency_points="1",
            ),
        )

        self.assertRedirects(
            response,
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
        )
        self.group.scoring_settings.refresh_from_db()
        self.assertEqual(
            (
                self.group.scoring_settings.exact_points,
                self.group.scoring_settings.goal_difference_points,
                self.group.scoring_settings.tendency_points,
                self.group.scoring_settings.incorrect_points,
            ),
            (5, 3, 1, 0),
        )

    def test_free_group_cannot_change_scoring(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
            self.scoring_payload(),
            follow=True,
        )

        self.assertContains(
            response,
            "requiere un plan Plus o Club activo",
        )
        self.group.scoring_settings.refresh_from_db()
        self.assertEqual(
            self.group.scoring_settings.exact_points,
            4,
        )

    def test_regular_member_cannot_change_scoring(self):
        self.enable_paid_plan()
        self.client.force_login(self.member)

        response = self.client.post(
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
            self.scoring_payload(),
            follow=True,
        )

        self.assertContains(
            response,
            "No tienes permiso",
        )
        self.group.scoring_settings.refresh_from_db()
        self.assertEqual(
            self.group.scoring_settings.exact_points,
            4,
        )

    def test_values_must_follow_category_order(self):
        self.enable_paid_plan()
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
            self.scoring_payload(
                exact_points="2",
                goal_difference_points="4",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Los puntos deben descender",
        )

    def test_first_complete_prediction_locks_scoring(self):
        self.enable_paid_plan()
        match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=timezone.now() + timedelta(days=1),
            matchday=1,
        )

        Prediction.objects.create(
            group=self.group,
            user=self.owner,
            match=match,
            pred_home=2,
            pred_away=1,
        )

        self.group.scoring_settings.refresh_from_db()
        self.assertTrue(
            self.group.scoring_settings.is_locked
        )

        self.group.scoring_settings.exact_points = 8
        with self.assertRaises(ValidationError):
            self.group.scoring_settings.save()

    def test_expired_plan_keeps_selected_scoring(self):
        self.enable_paid_plan()
        scoring_settings = self.group.scoring_settings
        scoring_settings.exact_points = 8
        scoring_settings.goal_difference_points = 5
        scoring_settings.tendency_points = 2
        scoring_settings.save()

        self.group.plan_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.group.save(update_fields=["plan_expires_at"])

        match = Match(
            home_score=2,
            away_score=1,
        )
        prediction = Prediction(
            group=self.group,
            pred_home=2,
            pred_away=1,
        )

        self.assertEqual(
            points_for_prediction(match, prediction),
            8,
        )


class GroupSpecificScoringTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(
            username="custom-score-a",
            password="test-password-123",
        )
        self.user_b = User.objects.create_user(
            username="custom-score-b",
            password="test-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Liga compartida",
        )
        self.group_a = Group.objects.create(
            name="Puntero estándar",
            tournament=self.tournament,
            owner=self.user_a,
        )
        self.group_b = Group.objects.create(
            name="Exactos fuertes",
            tournament=self.tournament,
            owner=self.user_b,
        )
        GroupMembership.objects.create(
            group=self.group_a,
            user=self.user_a,
            is_creator=True,
        )
        GroupMembership.objects.create(
            group=self.group_b,
            user=self.user_b,
            is_creator=True,
        )
        custom = self.group_b.scoring_settings
        custom.exact_points = 8
        custom.goal_difference_points = 4
        custom.tendency_points = 1
        custom.save()
        self.match = Match.objects.create(
            tournament=self.tournament,
            home_team="Local",
            away_team="Visitante",
            kickoff=timezone.now() - timedelta(days=1),
            matchday=1,
        )

    def test_same_match_uses_each_groups_scoring(self):
        prediction_a = Prediction.objects.create(
            group=self.group_a,
            user=self.user_a,
            match=self.match,
            pred_home=2,
            pred_away=1,
        )
        prediction_b = Prediction.objects.create(
            group=self.group_b,
            user=self.user_b,
            match=self.match,
            pred_home=2,
            pred_away=1,
        )
        Match.objects.filter(pk=self.match.pk).update(
            home_score=2,
            away_score=1,
        )
        self.match.refresh_from_db()

        recalculate_points_for_match(self.match)
        prediction_a.refresh_from_db()
        prediction_b.refresh_from_db()

        self.assertEqual(prediction_a.points, 4)
        self.assertEqual(prediction_b.points, 8)
        self.assertEqual(
            prediction_b.score_category,
            Prediction.ScoreCategory.EXACT,
        )

        rebuild_matchday_scores(
            group_id=self.group_b.id,
            matchday=1,
        )
        rebuild_group_standing(
            group_id=self.group_b.id,
        )

        score = MatchdayScore.objects.get(
            group=self.group_b,
            user=self.user_b,
            matchday=1,
        )
        standing = GroupStanding.objects.get(
            group=self.group_b,
            user=self.user_b,
        )

        self.assertEqual(score.points, 8)
        self.assertEqual(score.exact_predictions, 1)
        self.assertEqual(standing.exact_predictions, 1)

    def test_incorrect_category_is_independent_from_positive_points(self):
        custom = self.group_b.scoring_settings
        custom.incorrect_points = 1
        custom.tendency_points = 1
        custom.save()
        prediction = Prediction.objects.create(
            group=self.group_b,
            user=self.user_b,
            match=self.match,
            pred_home=0,
            pred_away=2,
        )
        Match.objects.filter(pk=self.match.pk).update(
            home_score=2,
            away_score=1,
        )
        self.match.refresh_from_db()

        recalculate_points_for_match(self.match)
        prediction.refresh_from_db()

        self.assertEqual(prediction.points, 1)
        self.assertEqual(
            prediction.score_category,
            Prediction.ScoreCategory.INCORRECT,
        )

    def test_rules_page_shows_active_groups_values(self):
        self.client.force_login(self.user_b)
        session = self.client.session
        session["active_group_id"] = self.group_b.id
        session.save()

        response = self.client.get(reverse("rules"))

        self.assertContains(
            response,
            "Estás viendo el sistema de puntuación",
        )
        self.assertContains(response, self.group_b.name)
        self.assertContains(response, "2:1 = 8 puntos")

    def test_backfill_clears_points_and_category_without_result(self):
        prediction = Prediction.objects.create(
            group=self.group_a,
            user=self.user_a,
            match=self.match,
            pred_home=2,
            pred_away=1,
        )
        Prediction.objects.filter(pk=prediction.pk).update(
            points=4,
            score_category=Prediction.ScoreCategory.EXACT,
        )

        call_command(
            "backfill_prediction_points",
            stdout=StringIO(),
        )

        prediction.refresh_from_db()
        self.assertIsNone(prediction.points)
        self.assertIsNone(prediction.score_category)
