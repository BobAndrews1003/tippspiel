from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tipping.forms import GroupCreateForm
from tipping.models import (
    Group,
    GroupMembership,
    GroupStanding,
    GroupTournamentSelection,
    Match,
    MatchdayScore,
    Prediction,
    Season,
    Tournament,
)
from tipping.standings import (
    rebuild_group_standing,
    rebuild_group_timeline,
    rebuild_matchday_scores,
)
from tipping.result_processing import process_match_change


class MultiTournamentGroupTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="multi-owner",
            password="test-password-123",
        )
        self.second_user = User.objects.create_user(
            username="multi-second",
            password="test-password-123",
        )
        self.season = Season.objects.create(
            name="Temporada 2027",
            year=2027,
        )
        self.ligapro = Tournament.objects.create(
            season=self.season,
            name="LigaPro 2027",
            code="ligapro",
        )
        self.copa = Tournament.objects.create(
            season=self.season,
            name="Copa Ecuador 2027",
            code="copa-ecuador",
        )
        self.league_cup = Tournament.objects.create(
            season=self.season,
            name="Copa de la Liga 2027",
            code="copa-de-la-liga",
        )
        self.group = Group.objects.create(
            name="Tres torneos",
            owner=self.user,
            tournament=self.ligapro,
        )
        GroupTournamentSelection.objects.create(
            group=self.group,
            tournament=self.copa,
            sort_order=2,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.user,
            is_creator=True,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.second_user,
        )

    def _match(self, tournament, *, day, home, away):
        return Match.objects.create(
            tournament=tournament,
            home_team=home,
            away_team=away,
            kickoff=timezone.now() - timedelta(days=day),
            matchday=1,
            home_score=1,
            away_score=0,
        )

    def test_prediction_accepts_each_selected_tournament(self):
        selected_match = self._match(
            self.copa,
            day=2,
            home="Copa Local",
            away="Copa Visitante",
        )
        prediction = Prediction.objects.create(
            user=self.user,
            group=self.group,
            match=selected_match,
            pred_home=1,
            pred_away=0,
        )

        selection = GroupTournamentSelection.objects.get(
            group=self.group,
            tournament=self.copa,
        )
        self.assertIsNotNone(selection.locked_at)
        self.assertEqual(prediction.match.tournament, self.copa)

        unselected_match = self._match(
            self.league_cup,
            day=1,
            home="Copa Liga Local",
            away="Copa Liga Visitante",
        )

        with self.assertRaises(ValidationError):
            Prediction.objects.create(
                user=self.user,
                group=self.group,
                match=unselected_match,
                pred_home=1,
                pred_away=0,
            )

    def test_same_matchday_number_is_separated_and_combined(self):
        league_match = self._match(
            self.ligapro,
            day=3,
            home="Liga Local",
            away="Liga Visitante",
        )
        cup_match = self._match(
            self.copa,
            day=2,
            home="Copa Local",
            away="Copa Visitante",
        )

        for user, league_points, cup_points in (
            (self.user, 4, 2),
            (self.second_user, 0, 4),
        ):
            Prediction.objects.create(
                user=user,
                group=self.group,
                match=league_match,
                pred_home=1,
                pred_away=0,
                points=league_points,
            )
            Prediction.objects.create(
                user=user,
                group=self.group,
                match=cup_match,
                pred_home=1,
                pred_away=0,
                points=cup_points,
            )

        rebuild_matchday_scores(
            group_id=self.group.id,
            tournament_id=self.ligapro.id,
            matchday=1,
        )
        rebuild_matchday_scores(
            group_id=self.group.id,
            tournament_id=self.copa.id,
            matchday=1,
        )
        rebuild_group_timeline(group_id=self.group.id)
        rebuild_group_standing(group_id=self.group.id)

        self.assertEqual(
            MatchdayScore.objects.filter(
                group=self.group,
                user=self.user,
                matchday=1,
            ).count(),
            2,
        )
        owner_standing = GroupStanding.objects.get(
            group=self.group,
            user=self.user,
        )
        second_standing = GroupStanding.objects.get(
            group=self.group,
            user=self.second_user,
        )
        self.assertEqual(owner_standing.match_points, 6)
        self.assertEqual(second_standing.match_points, 4)

    def test_result_processing_rebuilds_groups_that_selected_competition(self):
        cup_match = self._match(
            self.copa,
            day=2,
            home="Copa Local",
            away="Copa Visitante",
        )
        Prediction.objects.create(
            user=self.user,
            group=self.group,
            match=cup_match,
            pred_home=1,
            pred_away=0,
        )

        processed_groups = process_match_change(
            match_id=cup_match.id,
            rebuild_bonus=False,
        )

        self.assertEqual(processed_groups, 1)
        score = MatchdayScore.objects.get(
            group=self.group,
            user=self.user,
            tournament=self.copa,
            matchday=1,
        )
        self.assertEqual(score.points, 4)

    def test_competition_query_parameter_switches_prediction_page(self):
        self._match(
            self.ligapro,
            day=3,
            home="Liga Local",
            away="Liga Visitante",
        )
        self._match(
            self.copa,
            day=2,
            home="Copa Local",
            away="Copa Visitante",
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_group_id"] = self.group.id
        session.save()

        response = self.client.get(
            reverse("tippen"),
            {"competition": self.copa.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Copa Local")
        self.assertNotContains(response, "Liga Local")
        self.assertContains(response, "Copa Ecuador 2027")


class MultiTournamentGroupCreationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="group-creator",
            password="test-password-123",
        )
        self.season_2027 = Season.objects.create(
            name="Temporada 2027",
            year=2027,
        )
        self.season_2028 = Season.objects.create(
            name="Temporada 2028",
            year=2028,
        )
        self.ligapro = Tournament.objects.create(
            season=self.season_2027,
            name="LigaPro 2027",
            code="ligapro",
        )
        self.copa = Tournament.objects.create(
            season=self.season_2027,
            name="Copa Ecuador 2027",
            code="copa-ecuador",
        )
        self.future = Tournament.objects.create(
            season=self.season_2028,
            name="LigaPro 2028",
            code="ligapro",
        )

    def test_create_view_saves_all_selected_competitions(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("create_group"),
            {
                "name": "Combinada 2027",
                "tournaments": [
                    self.copa.id,
                    self.ligapro.id,
                ],
            },
        )

        self.assertRedirects(response, reverse("tippen"))
        group = Group.objects.get(name="Combinada 2027")
        self.assertEqual(group.tournament, self.ligapro)
        self.assertEqual(
            list(
                group.tournament_selections
                .order_by("sort_order")
                .values_list("tournament_id", flat=True)
            ),
            [self.ligapro.id, self.copa.id],
        )

    def test_form_rejects_competitions_from_different_seasons(self):
        form = GroupCreateForm(
            data={
                "name": "Mezcla inválida",
                "tournaments": [
                    self.ligapro.id,
                    self.future.id,
                ],
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("tournaments", form.errors)
