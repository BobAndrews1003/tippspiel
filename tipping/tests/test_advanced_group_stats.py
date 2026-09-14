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
    MatchdayScore,
    Prediction,
    Tournament,
)


User = get_user_model()


class AdvancedGroupStatsTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.owner = User.objects.create_user(
            username="stats-owner",
            email="owner-private@example.com",
            password="owner-password-123",
        )
        self.member = User.objects.create_user(
            username="stats-member",
            email="member-private@example.com",
            password="member-password-123",
        )
        self.outsider = User.objects.create_user(
            username="stats-outsider",
            password="outsider-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Liga de análisis",
        )
        self.group = Group.objects.create(
            name="Grupo de análisis",
            tournament=self.tournament,
            owner=self.owner,
            plan=Group.Plan.PLUS,
            plan_expires_at=self.now + timedelta(days=30),
        )
        self.owner_membership = GroupMembership.objects.create(
            user=self.owner,
            group=self.group,
            is_creator=True,
        )
        self.member_membership = GroupMembership.objects.create(
            user=self.member,
            group=self.group,
        )
        GroupMembership.all_objects.filter(
            pk__in=[
                self.owner_membership.pk,
                self.member_membership.pk,
            ]
        ).update(joined_at=self.now - timedelta(days=10))
        self.owner_membership.refresh_from_db()
        self.member_membership.refresh_from_db()

        self.matchday_one = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=self.now - timedelta(days=4),
            matchday=1,
            home_score=1,
            away_score=0,
        )
        self.matchday_two = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo C",
            away_team="Equipo D",
            kickoff=self.now - timedelta(days=2),
            matchday=2,
            home_score=2,
            away_score=1,
        )
        self.future_match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo E",
            away_team="Equipo F",
            kickoff=self.now + timedelta(days=2),
            matchday=3,
        )

        Prediction.objects.bulk_create(
            [
                Prediction(
                    user=self.owner,
                    group=self.group,
                    match=self.matchday_one,
                    pred_home=2,
                    pred_away=0,
                    points=2,
                ),
                Prediction(
                    user=self.owner,
                    group=self.group,
                    match=self.matchday_two,
                    pred_home=2,
                    pred_away=1,
                    points=4,
                ),
                Prediction(
                    user=self.member,
                    group=self.group,
                    match=self.matchday_one,
                    pred_home=1,
                    pred_away=0,
                    points=4,
                ),
                Prediction(
                    user=self.owner,
                    group=self.group,
                    match=self.future_match,
                    pred_home=9,
                    pred_away=8,
                    points=None,
                ),
            ]
        )
        MatchdayScore.objects.bulk_create(
            [
                MatchdayScore(
                    group=self.group,
                    user=self.owner,
                    matchday=1,
                    points=2,
                    cumulative_points=2,
                    cumulative_matchday_wins=0,
                    rank=2,
                ),
                MatchdayScore(
                    group=self.group,
                    user=self.member,
                    matchday=1,
                    points=4,
                    cumulative_points=4,
                    cumulative_matchday_wins=1,
                    rank=1,
                ),
                MatchdayScore(
                    group=self.group,
                    user=self.owner,
                    matchday=2,
                    points=4,
                    cumulative_points=6,
                    cumulative_matchday_wins=1,
                    rank=1,
                ),
                MatchdayScore(
                    group=self.group,
                    user=self.member,
                    matchday=2,
                    points=0,
                    cumulative_points=4,
                    cumulative_matchday_wins=1,
                    rank=2,
                ),
            ]
        )
        self.url = reverse(
            "advanced_group_stats",
            args=[self.group.id],
        )

    def test_plus_member_can_view_advanced_statistics(self):
        self.client.force_login(self.member)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Análisis del grupo")
        self.assertContains(response, "Grupo de análisis")
        self.assertEqual(response.context["active_section"], "overview")
        self.assertContains(response, "Rendimiento del grupo")
        self.assertNotContains(response, "Comparar participantes")
        self.assertNotContains(response, "Participación por fecha")
        self.assertEqual(response.context["member_count"], 2)
        self.assertEqual(response.context["evaluated_matchday_count"], 2)
        self.assertEqual(response.context["evaluated_prediction_count"], 3)
        self.assertEqual(response.context["participation_rate"], 75)
        self.assertEqual(response.context["leader_changes"], 1)

    def test_sections_show_only_the_selected_task(self):
        self.client.force_login(self.member)

        compare_response = self.client.get(
            self.url,
            {"section": "compare"},
        )
        participation_response = self.client.get(
            self.url,
            {"section": "participation"},
        )

        self.assertEqual(compare_response.status_code, 200)
        self.assertEqual(
            compare_response.context["active_section"],
            "compare",
        )
        self.assertContains(compare_response, "Comparar participantes")
        self.assertContains(compare_response, "advancedPointsChart")
        self.assertNotContains(compare_response, "Rendimiento del grupo")
        self.assertNotContains(compare_response, "Participación por fecha")

        self.assertEqual(participation_response.status_code, 200)
        self.assertEqual(
            participation_response.context["active_section"],
            "participation",
        )
        self.assertContains(
            participation_response,
            "Participación por persona",
        )
        self.assertContains(
            participation_response,
            "Participación por fecha",
        )
        self.assertNotContains(
            participation_response,
            "Comparar participantes",
        )

    def test_unknown_section_falls_back_to_overview(self):
        self.client.force_login(self.member)

        response = self.client.get(
            self.url,
            {"section": "not-a-real-section"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_section"], "overview")
        self.assertContains(response, "Rendimiento del grupo")

    def test_free_and_expired_groups_cannot_open_feature(self):
        self.client.force_login(self.owner)
        self.group.plan = Group.Plan.FREE
        self.group.plan_expires_at = None
        self.group.save(update_fields=["plan", "plan_expires_at"])

        free_response = self.client.get(self.url)

        self.group.plan = Group.Plan.PLUS
        self.group.plan_expires_at = self.now - timedelta(seconds=1)
        self.group.save(update_fields=["plan", "plan_expires_at"])
        expired_response = self.client.get(self.url)

        self.assertEqual(free_response.status_code, 404)
        self.assertEqual(expired_response.status_code, 404)

    def test_non_member_cannot_view_group_statistics(self):
        self.client.force_login(self.outsider)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_comparison_accepts_only_members_of_the_group(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            self.url,
            {
                "player_a": self.member.id,
                "player_b": self.outsider.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["selected_player_a_id"],
            self.member.id,
        )
        self.assertEqual(
            response.context["selected_player_b_id"],
            self.owner.id,
        )
        self.assertNotContains(response, "stats-outsider")

    def test_future_prediction_and_emails_are_not_exposed(self):
        self.client.force_login(self.member)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "9:8")
        self.assertNotContains(response, "owner-private@example.com")
        self.assertNotContains(response, "Fecha 3")

    def test_report_metrics_use_precomputed_timeline(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            self.url,
            {
                "player_a": self.owner.id,
                "player_b": self.member.id,
            },
        )

        rows = {
            row["user_id"]: row
            for row in response.context["member_rows"]
        }
        owner_row = rows[self.owner.id]
        member_row = rows[self.member.id]

        self.assertEqual(owner_row["rank"], 1)
        self.assertEqual(owner_row["match_points"], 6)
        self.assertEqual(owner_row["average_points"], 3.0)
        self.assertEqual(owner_row["hit_rate"], 100)
        self.assertEqual(owner_row["exact_predictions"], 1)
        self.assertEqual(owner_row["best_matchday"], 2)
        self.assertEqual(member_row["participation_rate"], 50)
        self.assertEqual(
            response.context["comparison_series"][0]["points"],
            [2, 6],
        )
        self.assertEqual(
            response.context["comparison_series"][1]["ranks"],
            [1, 2],
        )

    def test_visible_bonus_is_used_in_report_but_not_timeline(self):
        GroupStanding.objects.bulk_create(
            [
                GroupStanding(
                    group=self.group,
                    user=self.owner,
                    match_points=6,
                    bonus_points=0,
                    total_points=6,
                    matchday_wins=1,
                ),
                GroupStanding(
                    group=self.group,
                    user=self.member,
                    match_points=4,
                    bonus_points=5,
                    total_points=9,
                    matchday_wins=1,
                ),
            ]
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            self.url,
            {
                "player_a": self.member.id,
                "player_b": self.owner.id,
            },
        )

        rows = {
            row["user_id"]: row
            for row in response.context["member_rows"]
        }
        self.assertTrue(response.context["bonus_reveal"])
        self.assertEqual(rows[self.member.id]["match_points"], 9)
        self.assertEqual(rows[self.member.id]["rank"], 1)
        self.assertEqual(rows[self.owner.id]["rank"], 2)
        self.assertEqual(
            response.context["comparison_series"][0]["points"],
            [4, 4],
        )
        self.assertContains(
            response,
            "incluyen el bonus ya visible",
        )

    def test_equal_points_and_wins_share_the_same_report_rank(self):
        GroupStanding.objects.bulk_create(
            [
                GroupStanding(
                    group=self.group,
                    user=self.owner,
                    match_points=10,
                    total_points=10,
                    matchday_wins=2,
                ),
                GroupStanding(
                    group=self.group,
                    user=self.member,
                    match_points=10,
                    total_points=10,
                    matchday_wins=2,
                ),
            ]
        )
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertEqual(
            [
                row["rank"]
                for row in response.context["member_rows"]
            ],
            [1, 1],
        )

    def test_matches_before_joining_do_not_lower_participation(self):
        late_member = User.objects.create_user(
            username="stats-late-member",
            password="late-password-123",
        )
        late_membership = GroupMembership.objects.create(
            user=late_member,
            group=self.group,
        )
        GroupMembership.all_objects.filter(
            pk=late_membership.pk,
        ).update(joined_at=self.now - timedelta(days=3))
        self.client.force_login(self.member)

        response = self.client.get(self.url)

        rows = {
            row["user_id"]: row
            for row in response.context["member_rows"]
        }
        self.assertEqual(
            rows[late_member.id]["expected_predictions"],
            1,
        )
        self.assertEqual(rows[late_member.id]["participation_rate"], 0)

    def test_advanced_statistics_reject_post(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)
