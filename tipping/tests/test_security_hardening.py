from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tipping.models import (
    Group,
    GroupMembership,
    Tournament,
)


User = get_user_model()


class SecurityHardeningTests(TestCase):

    def setUp(self):
        self.password = "Strong-Test-Password-4711"

        self.user = User.objects.create_user(
            username="security_owner",
            email="security-owner@example.com",
            password=self.password,
        )

        self.other_password = "Other-Strong-Password-4711"

        self.other_user = User.objects.create_user(
            username="security_member",
            email="security-member@example.com",
            password=self.other_password,
        )

        self.tournament = Tournament.objects.create(
            name="Security Test Tournament",
        )

        self.group = Group.objects.create(
            name="Security Test Group",
            tournament=self.tournament,
            owner=self.user,
        )

        GroupMembership.objects.create(
            user=self.user,
            group=self.group,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.other_user,
            group=self.group,
            is_creator=False,
        )

        self.client.force_login(self.user)


    def test_delete_group_rejects_get(self):
        response = self.client.get(
            reverse(
                "delete_group",
                args=[self.group.id],
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )

        self.assertTrue(
            Group.objects.filter(
                id=self.group.id,
            ).exists()
        )


    def test_set_active_group_rejects_oversized_id(self):
        response = self.client.post(
            reverse("set_active_group"),
            {
                "group_id": "9" * 5000,
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertNotEqual(
            self.client.session.get(
                "active_group_id"
            ),
            int("9" * 10),
        )


    def test_set_active_group_rejects_non_ascii_digits(self):
        response = self.client.post(
            reverse("set_active_group"),
            {
                "group_id": "１２３",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )


    def test_transfer_ownership_rejects_oversized_id(self):
        response = self.client.post(
            reverse(
                "transfer_group_ownership",
                args=[self.group.id],
            ),
            {
                "new_owner_id": "9" * 5000,
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.group.refresh_from_db()

        self.assertEqual(
            self.group.owner_id,
            self.user.id,
        )


    def test_read_only_dashboard_rejects_post(self):
        response = self.client.post(
            reverse("dashboard")
        )

        self.assertEqual(
            response.status_code,
            405,
        )


    def test_admin_requires_allauth_login(self):
        self.client.logout()

        response = self.client.get(
            reverse("admin:login"),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            response["Location"].startswith(
                reverse("account_login")
            ),
            response["Location"],
        )


    def test_account_deletion_clears_auth_session(self):
        # Der Gruppenadministrator darf sein Konto absichtlich
        # nicht löschen. Deshalb verwenden wir hier ein normales
        # Gruppenmitglied ohne eigene Gruppen.
        self.client.logout()
        self.client.force_login(self.other_user)

        response = self.client.post(
            reverse("delete_account"),
            {
                "password": self.other_password,
                "confirmation": "ELIMINAR",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            User.objects.filter(
                username="security_member"
            ).exists()
        )

        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )
