from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    Tournament,
)


User = get_user_model()


class GroupCoAdminTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="coadmin-owner",
            password="owner-password-123",
        )
        self.co_admin = User.objects.create_user(
            username="coadmin-assistant",
            password="assistant-password-123",
        )
        self.member = User.objects.create_user(
            username="coadmin-member",
            password="member-password-123",
        )
        self.other_co_admin = User.objects.create_user(
            username="coadmin-other",
            password="other-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Liga de coadministradores",
        )
        self.group = Group.objects.create(
            name="Grupo Plus",
            tournament=self.tournament,
            owner=self.owner,
            plan=Group.Plan.PLUS,
            plan_expires_at=(
                timezone.now() + timedelta(days=30)
            ),
        )
        self.owner_membership = GroupMembership.objects.create(
            user=self.owner,
            group=self.group,
            is_creator=True,
        )
        self.co_admin_membership = GroupMembership.objects.create(
            user=self.co_admin,
            group=self.group,
        )
        self.member_membership = GroupMembership.objects.create(
            user=self.member,
            group=self.group,
        )
        self.other_co_admin_membership = (
            GroupMembership.objects.create(
                user=self.other_co_admin,
                group=self.group,
            )
        )

    def enable_co_admin(self, membership=None):
        membership = membership or self.co_admin_membership
        membership.is_co_admin = True
        membership.save(update_fields=["is_co_admin"])

    def test_owner_can_grant_and_revoke_co_admin_role(self):
        self.client.force_login(self.owner)
        role_url = reverse(
            "set_group_co_admin",
            args=[self.group.id, self.co_admin.id],
        )

        response = self.client.post(
            role_url,
            {"action": "grant"},
        )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.co_admin_membership.refresh_from_db()
        self.assertTrue(self.co_admin_membership.is_co_admin)

        response = self.client.post(
            role_url,
            {"action": "revoke"},
        )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.co_admin_membership.refresh_from_db()
        self.assertFalse(self.co_admin_membership.is_co_admin)

    def test_free_group_cannot_grant_co_admin_role(self):
        self.group.plan = Group.Plan.FREE
        self.group.plan_expires_at = None
        self.group.save(
            update_fields=["plan", "plan_expires_at"],
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "set_group_co_admin",
                args=[self.group.id, self.co_admin.id],
            ),
            {"action": "grant"},
        )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.co_admin_membership.refresh_from_db()
        self.assertFalse(self.co_admin_membership.is_co_admin)

    def test_regular_member_cannot_assign_co_admin_role(self):
        self.client.force_login(self.member)

        response = self.client.post(
            reverse(
                "set_group_co_admin",
                args=[self.group.id, self.member.id],
            ),
            {"action": "grant"},
        )

        self.assertRedirects(response, reverse("my_groups"))
        self.member_membership.refresh_from_db()
        self.assertFalse(self.member_membership.is_co_admin)

    def test_co_admin_can_edit_group_settings(self):
        self.enable_co_admin()
        self.client.force_login(self.co_admin)

        page = self.client.get(
            reverse("group_detail", args=[self.group.id]),
        )
        self.assertContains(page, "Coadministrador")
        self.assertContains(page, "Guardar configuración")

        response = self.client.post(
            reverse("group_detail", args=[self.group.id]),
            {
                "name": "Grupo gestionado",
                "join_enabled": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Grupo gestionado")
        self.assertTrue(self.group.join_enabled)

    def test_co_admin_can_rotate_invitation_code(self):
        self.enable_co_admin()
        old_code = self.group.join_code
        self.client.force_login(self.co_admin)

        response = self.client.post(
            reverse(
                "rotate_group_join_code",
                args=[self.group.id],
            )
        )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.group.refresh_from_db()
        self.assertNotEqual(self.group.join_code, old_code)

    def test_co_admin_can_remove_regular_member(self):
        self.enable_co_admin()
        self.client.force_login(self.co_admin)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse(
                    "remove_group_member",
                    args=[self.group.id, self.member.id],
                )
            )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.member_membership.refresh_from_db()
        self.assertFalse(self.member_membership.is_active)
        self.assertFalse(self.member_membership.is_co_admin)

    def test_co_admin_cannot_remove_another_co_admin(self):
        self.enable_co_admin()
        self.enable_co_admin(self.other_co_admin_membership)
        self.client.force_login(self.co_admin)

        response = self.client.post(
            reverse(
                "remove_group_member",
                args=[self.group.id, self.other_co_admin.id],
            )
        )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.other_co_admin_membership.refresh_from_db()
        self.assertTrue(self.other_co_admin_membership.is_active)
        self.assertTrue(self.other_co_admin_membership.is_co_admin)

    def test_expired_plan_pauses_co_admin_permissions(self):
        self.enable_co_admin()
        self.group.plan_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.group.save(update_fields=["plan_expires_at"])
        old_code = self.group.join_code
        self.client.force_login(self.co_admin)

        settings_response = self.client.post(
            reverse("group_detail", args=[self.group.id]),
            {
                "name": "No debe cambiar",
                "join_enabled": "on",
            },
        )
        rotate_response = self.client.post(
            reverse(
                "rotate_group_join_code",
                args=[self.group.id],
            )
        )

        self.assertRedirects(
            settings_response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.assertRedirects(rotate_response, reverse("my_groups"))
        self.group.refresh_from_db()
        self.co_admin_membership.refresh_from_db()
        self.assertEqual(self.group.name, "Grupo Plus")
        self.assertEqual(self.group.join_code, old_code)
        self.assertTrue(self.co_admin_membership.is_co_admin)

    def test_owner_can_revoke_role_after_plan_expires(self):
        self.enable_co_admin()
        self.group.plan_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.group.save(update_fields=["plan_expires_at"])
        self.client.force_login(self.owner)

        page = self.client.get(
            reverse("group_detail", args=[self.group.id]),
        )
        self.assertContains(page, "Coadministrador pausado")
        self.assertContains(page, "Quitar rol")

        response = self.client.post(
            reverse(
                "set_group_co_admin",
                args=[self.group.id, self.co_admin.id],
            ),
            {"action": "revoke"},
        )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.co_admin_membership.refresh_from_db()
        self.assertFalse(self.co_admin_membership.is_co_admin)

    def test_co_admin_cannot_transfer_or_delete_group(self):
        self.enable_co_admin()
        self.client.force_login(self.co_admin)

        transfer_response = self.client.post(
            reverse(
                "transfer_group_ownership",
                args=[self.group.id],
            ),
            {"new_owner_id": self.member.id},
        )
        delete_response = self.client.post(
            reverse("delete_group", args=[self.group.id]),
            {"confirmation": self.group.name},
        )

        self.assertRedirects(transfer_response, reverse("my_groups"))
        self.assertRedirects(delete_response, reverse("my_groups"))
        self.group.refresh_from_db()
        self.assertEqual(self.group.owner_id, self.owner.id)

    def test_owner_removing_co_admin_clears_role(self):
        self.enable_co_admin()
        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse(
                    "remove_group_member",
                    args=[self.group.id, self.co_admin.id],
                )
            )

        self.assertRedirects(
            response,
            reverse("group_detail", args=[self.group.id]),
        )
        self.co_admin_membership.refresh_from_db()
        self.assertFalse(self.co_admin_membership.is_active)
        self.assertFalse(self.co_admin_membership.is_co_admin)

    def test_co_admin_role_endpoint_rejects_get(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "set_group_co_admin",
                args=[self.group.id, self.co_admin.id],
            )
        )

        self.assertEqual(response.status_code, 405)

    def test_invalid_role_combinations_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.owner_membership.is_co_admin = True
            self.owner_membership.save(
                update_fields=["is_co_admin"],
            )

        self.co_admin_membership.is_active = False
        self.co_admin_membership.is_co_admin = True

        with self.assertRaises(ValidationError):
            self.co_admin_membership.save(
                update_fields=["is_active", "is_co_admin"],
            )
