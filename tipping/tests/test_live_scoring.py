from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    Prediction,
    Tournament,
)


class LiveScoringViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user_exact = User.objects.create_user(
            username="live-exact",
            password="test-password-123",
        )
        self.user_tendency = User.objects.create_user(
            username="live-tendency",
            password="test-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Live-Testturnier",
        )
        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Live-Testgruppe",
            owner=self.user_exact,
        )

        for user, is_creator in (
            (self.user_exact, True),
            (self.user_tendency, False),
        ):
            GroupMembership.objects.create(
                group=self.group,
                user=user,
                is_creator=is_creator,
            )

        self.match = Match.objects.create(
            tournament=self.tournament,
            home_team="Aucas",
            away_team="Macará",
            kickoff=timezone.now() - timedelta(minutes=30),
            matchday=1,
            external_source="ligapro_official",
            external_id="live-view-match",
            source_status=Match.SourceStatus.LIVE,
            live_home_score=1,
            live_away_score=0,
        )
        self.exact_prediction = Prediction.objects.create(
            group=self.group,
            user=self.user_exact,
            match=self.match,
            pred_home=1,
            pred_away=0,
        )
        self.tendency_prediction = Prediction.objects.create(
            group=self.group,
            user=self.user_tendency,
            match=self.match,
            pred_home=2,
            pred_away=0,
        )

        self.client.login(
            username="live-exact",
            password="test-password-123",
        )
        session = self.client.session
        session["active_group_id"] = self.group.id
        session.save()

    def test_current_matchday_shows_live_points_and_rank(self):
        response = self.client.get(
            reverse("spieltag"),
            {"md": 1},
        )

        self.assertEqual(response.status_code, 200)
        rows = response.context["table_rows"]

        self.assertEqual(
            [row["user"].username for row in rows],
            ["live-exact", "live-tendency"],
        )
        self.assertEqual(
            [row["total_points"] for row in rows],
            [4, 2],
        )
        self.assertEqual(
            [row["position"] for row in rows],
            [1, 2],
        )
        self.assertEqual(
            [row["cells"][0]["points"] for row in rows],
            [4, 2],
        )
        self.assertTrue(response.context["has_live_matches"])
        self.assertContains(response, "EN VIVO")
        self.assertContains(response, "window.location.reload()")

    def test_live_points_do_not_change_persisted_overall_standing(self):
        self.exact_prediction.refresh_from_db()
        self.tendency_prediction.refresh_from_db()

        self.assertIsNone(self.exact_prediction.points)
        self.assertIsNone(self.tendency_prediction.points)

        for user in (
            self.user_exact,
            self.user_tendency,
        ):
            standing = GroupStanding.objects.filter(
                group=self.group,
                user=user,
            ).first()

            if standing is not None:
                self.assertEqual(standing.match_points, 0)

    def test_equal_live_points_share_the_same_rank(self):
        self.tendency_prediction.pred_home = 1
        self.tendency_prediction.pred_away = 0
        self.tendency_prediction.save(
            update_fields=[
                "pred_home",
                "pred_away",
            ]
        )

        response = self.client.get(
            reverse("spieltag"),
            {"md": 1},
        )

        self.assertEqual(response.status_code, 200)
        rows = response.context["table_rows"]
        self.assertEqual(
            [row["total_points"] for row in rows],
            [4, 4],
        )
        self.assertEqual(
            [row["position"] for row in rows],
            [1, 1],
        )
