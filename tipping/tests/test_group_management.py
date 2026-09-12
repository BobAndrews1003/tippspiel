from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
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


User = get_user_model()


class GroupManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="group-owner",
            email="owner-secret@example.com",
            password="owner-password-123",
        )
        self.member = User.objects.create_user(
            username="group-member",
            email="member-secret@example.com",
            password="member-password-123",
        )
        self.outsider = User.objects.create_user(
            username="group-outsider",
            email="outsider-secret@example.com",
            password="outsider-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Liga de prueba",
            season_start=(
                timezone.now()
                - timedelta(days=10)
            ),
        )
        self.group = Group.objects.create(
            name="Amigos de Puntero",
            tournament=self.tournament,
            owner=self.owner,
        )
        self.owner_membership = (
            GroupMembership.objects.create(
                user=self.owner,
                group=self.group,
                is_creator=True,
            )
        )
        self.member_membership = (
            GroupMembership.objects.create(
                user=self.member,
                group=self.group,
            )
        )

    def test_member_can_open_detail_without_seeing_email_addresses(
        self,
    ):
        self.client.force_login(self.member)

        response = self.client.get(
            reverse(
                "group_detail",
                args=[self.group.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "group-owner")
        self.assertContains(response, "group-member")
        self.assertNotContains(
            response,
            "owner-secret@example.com",
        )
        self.assertNotContains(
            response,
            "Guardar configuración",
        )

    def test_non_member_cannot_open_group_detail(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse(
                "group_detail",
                args=[self.group.id],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_can_rename_group_and_close_joining(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
            {
                "name": "  Nuevo nombre  ",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
        )

        self.group.refresh_from_db()
        self.assertEqual(
            self.group.name,
            "Nuevo nombre",
        )
        self.assertFalse(self.group.join_enabled)

    def test_member_cannot_change_group_settings(self):
        self.client.force_login(self.member)

        response = self.client.post(
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
            {
                "name": "Nombre manipulado",
                "join_enabled": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
        )

        self.group.refresh_from_db()
        self.assertEqual(
            self.group.name,
            "Amigos de Puntero",
        )

    def test_closed_group_rejects_new_member(self):
        self.group.join_enabled = False
        self.group.save(
            update_fields=["join_enabled"],
        )
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("join_group"),
            {"code": self.group.join_code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "no admite nuevos participantes",
        )
        self.assertFalse(
            GroupMembership.objects.filter(
                group=self.group,
                user=self.outsider,
            ).exists()
        )

    def test_invitation_link_prefills_join_code(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("join_group"),
            {"code": self.group.join_code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'value="{self.group.join_code}"',
            html=False,
        )

    def test_owner_can_rotate_code_and_old_code_stops_working(self):
        old_code = self.group.join_code
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "rotate_group_join_code",
                args=[self.group.id],
            )
        )

        self.assertRedirects(
            response,
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
        )
        self.group.refresh_from_db()
        self.assertNotEqual(
            self.group.join_code,
            old_code,
        )

        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse("join_group"),
            {"code": old_code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            GroupMembership.objects.filter(
                group=self.group,
                user=self.outsider,
            ).exists()
        )

    def test_member_cannot_rotate_join_code(self):
        old_code = self.group.join_code
        self.client.force_login(self.member)

        response = self.client.post(
            reverse(
                "rotate_group_join_code",
                args=[self.group.id],
            )
        )

        self.assertRedirects(
            response,
            reverse("my_groups"),
        )
        self.group.refresh_from_db()
        self.assertEqual(
            self.group.join_code,
            old_code,
        )

    def test_remove_member_preserves_tips_and_rotates_code(self):
        match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=timezone.now() + timedelta(days=2),
            matchday=1,
        )
        prediction = Prediction.objects.create(
            user=self.member,
            group=self.group,
            match=match,
            pred_home=2,
            pred_away=1,
        )
        bonus_prediction = BonusPrediction.objects.create(
            user=self.member,
            group=self.group,
            bonus_type="meister",
            value="Equipo A",
        )
        GroupStanding.objects.update_or_create(
            group=self.group,
            user=self.member,
            defaults={
                "match_points": 4,
                "total_points": 4,
            },
        )
        old_code = self.group.join_code
        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            response = self.client.post(
                reverse(
                    "remove_group_member",
                    args=[
                        self.group.id,
                        self.member.id,
                    ],
                )
            )

        self.assertRedirects(
            response,
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
        )
        self.assertFalse(
            GroupMembership.objects.filter(
                group=self.group,
                user=self.member,
            ).exists()
        )
        inactive_membership = (
            GroupMembership.all_objects.get(
                group=self.group,
                user=self.member,
            )
        )
        self.assertFalse(
            inactive_membership.is_active
        )
        self.assertIsNotNone(
            inactive_membership.removed_at
        )
        self.assertTrue(
            Prediction.objects.filter(pk=prediction.pk).exists()
        )
        self.assertTrue(
            BonusPrediction.objects.filter(
                pk=bonus_prediction.pk,
            ).exists()
        )
        self.assertFalse(
            GroupStanding.objects.filter(
                group=self.group,
                user=self.member,
            ).exists()
        )

        self.group.refresh_from_db()
        self.assertNotEqual(
            self.group.join_code,
            old_code,
        )

    def test_removed_member_can_rejoin_with_new_invitation(self):
        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            self.client.post(
                reverse(
                    "remove_group_member",
                    args=[
                        self.group.id,
                        self.member.id,
                    ],
                )
            )

        self.group.refresh_from_db()
        new_code = self.group.join_code
        self.client.force_login(self.member)

        with self.captureOnCommitCallbacks(
            execute=True,
        ):
            response = self.client.post(
                reverse("join_group"),
                {"code": new_code},
            )

        self.assertRedirects(
            response,
            reverse("tippen"),
            fetch_redirect_response=False,
        )
        membership = GroupMembership.objects.get(
            group=self.group,
            user=self.member,
        )
        self.assertTrue(membership.is_active)
        self.assertIsNone(membership.removed_at)
        self.assertEqual(
            GroupMembership.all_objects.filter(
                group=self.group,
                user=self.member,
            ).count(),
            1,
        )

    def test_owner_cannot_remove_self(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "remove_group_member",
                args=[
                    self.group.id,
                    self.owner.id,
                ],
            )
        )

        self.assertRedirects(
            response,
            reverse(
                "group_detail",
                args=[self.group.id],
            ),
        )
        self.assertTrue(
            GroupMembership.objects.filter(
                group=self.group,
                user=self.owner,
            ).exists()
        )

    def test_rank_uses_matchday_wins_and_keeps_exact_ties(self):
        tied_user = User.objects.create_user(
            username="group-tied",
            password="tied-password-123",
        )
        GroupMembership.objects.create(
            user=tied_user,
            group=self.group,
        )

        GroupStanding.objects.update_or_create(
            group=self.group,
            user=self.owner,
            defaults={
                "match_points": 10,
                "total_points": 10,
                "matchday_wins": 2,
            },
        )
        GroupStanding.objects.update_or_create(
            group=self.group,
            user=self.member,
            defaults={
                "match_points": 10,
                "total_points": 10,
                "matchday_wins": 1,
            },
        )
        GroupStanding.objects.update_or_create(
            group=self.group,
            user=tied_user,
            defaults={
                "match_points": 10,
                "total_points": 10,
                "matchday_wins": 2,
            },
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "group_detail",
                args=[self.group.id],
            )
        )

        rows = response.context["member_rows"]
        rank_by_name = {
            row["display_name"]: row["rank"]
            for row in rows
        }

        self.assertEqual(rank_by_name["group-owner"], 1)
        self.assertEqual(rank_by_name["group-tied"], 1)
        self.assertEqual(rank_by_name["group-member"], 3)

    def test_destructive_group_actions_reject_get(self):
        self.client.force_login(self.owner)

        rotate_response = self.client.get(
            reverse(
                "rotate_group_join_code",
                args=[self.group.id],
            )
        )
        remove_response = self.client.get(
            reverse(
                "remove_group_member",
                args=[
                    self.group.id,
                    self.member.id,
                ],
            )
        )

        self.assertEqual(rotate_response.status_code, 405)
        self.assertEqual(remove_response.status_code, 405)

    def test_activate_group_honors_safe_local_destination(self):
        second_group = Group.objects.create(
            name="Segundo grupo",
            tournament=self.tournament,
            owner=self.owner,
        )
        GroupMembership.objects.create(
            user=self.owner,
            group=second_group,
            is_creator=True,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("set_active_group"),
            {
                "group_id": second_group.id,
                "next": reverse("tabelle"),
            },
        )

        self.assertRedirects(
            response,
            reverse("tabelle"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.session["active_group_id"],
            second_group.id,
        )

    def test_activate_group_rejects_external_destination(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("set_active_group"),
            {
                "group_id": self.group.id,
                "next": "https://evil.example/phishing",
            },
        )

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )
