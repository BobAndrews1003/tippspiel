from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tipping.group_plans import (
    group_has_entitlement,
    group_member_limit,
)
from tipping.models import (
    Group,
    GroupMembership,
    Tournament,
)


User = get_user_model()


class GroupPlanModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="plan-owner",
            password="owner-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Liga de planes",
        )

    def create_group(self, **kwargs):
        return Group.objects.create(
            name="Grupo con plan",
            tournament=self.tournament,
            owner=self.owner,
            **kwargs,
        )

    def test_new_group_starts_with_free_plan(self):
        group = self.create_group()

        self.assertEqual(group.plan, Group.Plan.FREE)
        self.assertEqual(group.effective_plan, "free")
        self.assertEqual(group.effective_plan_label, "Free")

    def test_active_plus_plan_exposes_entitlements(self):
        group = self.create_group(
            plan=Group.Plan.PLUS,
            plan_expires_at=(
                timezone.now() + timedelta(days=30)
            ),
        )

        self.assertEqual(group.effective_plan, "plus")
        self.assertTrue(
            group_has_entitlement(
                group,
                "co_admins",
            )
        )
        self.assertTrue(
            group_has_entitlement(
                group,
                "advanced_stats",
            )
        )
        self.assertFalse(
            group_has_entitlement(
                group,
                "advanced_exports",
            )
        )
        self.assertFalse(
            group_has_entitlement(
                group,
                "branding",
            )
        )

    def test_expired_paid_plan_falls_back_to_free(self):
        group = self.create_group(
            plan=Group.Plan.CLUB,
            plan_expires_at=(
                timezone.now() - timedelta(seconds=1)
            ),
        )

        self.assertEqual(group.plan, Group.Plan.CLUB)
        self.assertEqual(group.effective_plan, "free")
        self.assertFalse(
            group_has_entitlement(
                group,
                "branding",
            )
        )

    @override_settings(
        GROUP_PLAN_LIMITS_ENABLED=False,
        GROUP_PLAN_FREE_MEMBER_LIMIT=20,
    )
    def test_member_limit_is_disabled_for_private_test(self):
        group = self.create_group()

        self.assertIsNone(group_member_limit(group))


class GroupPlanViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="view-owner",
            password="owner-password-123",
        )
        self.member = User.objects.create_user(
            username="view-member",
            password="member-password-123",
        )
        self.outsider = User.objects.create_user(
            username="view-outsider",
            password="outsider-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Liga de vista previa",
        )
        self.group = Group.objects.create(
            name="Grupo lleno",
            tournament=self.tournament,
            owner=self.owner,
        )
        GroupMembership.objects.create(
            user=self.owner,
            group=self.group,
            is_creator=True,
        )
        GroupMembership.objects.create(
            user=self.member,
            group=self.group,
        )

    @override_settings(GROUP_PLANS_ENABLED=False)
    def test_plan_page_is_hidden_by_default(self):
        response = self.client.get(reverse("group_plans"))

        self.assertEqual(response.status_code, 404)

    @override_settings(
        GROUP_PLANS_ENABLED=True,
        GROUP_PLAN_LIMITS_ENABLED=False,
        GROUP_PLAN_FREE_MEMBER_LIMIT=20,
        GROUP_PLAN_PLUS_MEMBER_LIMIT=100,
        GROUP_PLAN_PLUS_PRICE_USD=12,
        GROUP_PLAN_CLUB_PRICE_USD=99,
    )
    def test_plan_preview_is_transparent_about_unavailable_sales(self):
        response = self.client.get(reverse("group_plans"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Free")
        self.assertContains(response, "Plus")
        self.assertContains(response, "Club")
        self.assertContains(
            response,
            "todavía no hay pagos",
        )
        self.assertContains(response, "Próximamente")

    @override_settings(
        GROUP_PLANS_ENABLED=True,
        GROUP_PLAN_LIMITS_ENABLED=True,
        GROUP_PLAN_FREE_MEMBER_LIMIT=2,
        GROUP_PLAN_PLUS_MEMBER_LIMIT=3,
    )
    def test_enabled_free_limit_blocks_only_new_members(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("join_group"),
            {"code": self.group.join_code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "límite de 2 participantes",
        )
        self.assertFalse(
            GroupMembership.objects.filter(
                group=self.group,
                user=self.outsider,
            ).exists()
        )

    @override_settings(
        GROUP_PLANS_ENABLED=True,
        GROUP_PLAN_LIMITS_ENABLED=False,
        GROUP_PLAN_FREE_MEMBER_LIMIT=2,
        GROUP_PLAN_PLUS_MEMBER_LIMIT=3,
    )
    def test_disabled_limits_keep_existing_join_flow_unchanged(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("join_group"),
            {"code": self.group.join_code},
        )

        self.assertRedirects(
            response,
            reverse("tippen"),
            fetch_redirect_response=False,
        )
        self.assertTrue(
            GroupMembership.objects.filter(
                group=self.group,
                user=self.outsider,
            ).exists()
        )
