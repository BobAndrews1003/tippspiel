from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from tipping.models import (
    Group,
    GroupBranding,
    GroupMembership,
    Tournament,
)


User = get_user_model()


class GroupBrandingTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.media_override = override_settings(
            MEDIA_ROOT=self.media_directory.name,
        )
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_directory.cleanup)

        self.owner = User.objects.create_user(
            username="brand-owner",
            password="owner-password-123",
        )
        self.member = User.objects.create_user(
            username="brand-member",
            password="member-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="Liga corporativa",
        )
        self.group = Group.objects.create(
            name="Empresa Puntero",
            tournament=self.tournament,
            owner=self.owner,
            plan=Group.Plan.CLUB,
            plan_expires_at=(
                timezone.now() + timedelta(days=30)
            ),
        )
        GroupMembership.objects.create(
            user=self.owner,
            group=self.group,
            is_creator=True,
        )
        self.member_membership = GroupMembership.objects.create(
            user=self.member,
            group=self.group,
        )
        self.url = reverse(
            "group_detail",
            args=[self.group.id],
        )

    def image_upload(
        self,
        *,
        width=120,
        height=80,
        filename="company-logo.png",
    ):
        buffer = BytesIO()
        Image.new(
            "RGB",
            (width, height),
            "#ffffff",
        ).save(buffer, format="PNG")

        return SimpleUploadedFile(
            filename,
            buffer.getvalue(),
            content_type="image/png",
        )

    def branding_payload(self, **overrides):
        payload = {
            "form_action": "branding",
            "primary_color": "#2FBF83",
            "accent_color": "#E88A2D",
            "background_color": "#223451",
            "theme_mode": "light",
            "brand_intensity": "strong",
            "welcome_text": (
                "Bienvenidos al torneo interno de la empresa."
            ),
        }
        payload.update(overrides)
        return payload

    def activate_group(self):
        session = self.client.session
        session["active_group_id"] = self.group.id
        session.save()

    def test_owner_can_save_and_see_club_branding(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            self.branding_payload(
                logo=self.image_upload(),
                hero_image=self.image_upload(
                    width=1200,
                    height=600,
                    filename="company-hero.png",
                ),
            ),
        )

        self.assertRedirects(response, self.url)
        branding = GroupBranding.objects.get(
            group=self.group
        )
        self.assertEqual(branding.primary_color, "#2FBF83")
        self.assertEqual(branding.accent_color, "#E88A2D")
        self.assertEqual(branding.background_color, "#223451")
        self.assertEqual(
            branding.theme_mode,
            GroupBranding.ThemeMode.LIGHT,
        )
        self.assertEqual(
            branding.brand_intensity,
            GroupBranding.BrandIntensity.STRONG,
        )
        self.assertEqual(
            branding.welcome_text,
            "Bienvenidos al torneo interno de la empresa.",
        )
        self.assertNotIn(
            "company-logo",
            branding.logo.name,
        )
        self.assertNotIn(
            "company-hero",
            branding.hero_image.name,
        )

        self.activate_group()
        dashboard_response = self.client.get(
            reverse("dashboard")
        )

        self.assertContains(
            dashboard_response,
            "group-branding-active",
        )
        self.assertContains(
            dashboard_response,
            reverse(
                "group_branding_css",
                args=[self.group.id],
            ),
        )
        self.assertContains(
            dashboard_response,
            branding.welcome_text,
        )
        self.assertContains(
            dashboard_response,
            branding.logo.url,
        )
        self.assertContains(
            dashboard_response,
            branding.hero_image.url,
        )

    def test_co_admin_can_edit_branding(self):
        self.member_membership.is_co_admin = True
        self.member_membership.save(
            update_fields=["is_co_admin"]
        )
        self.client.force_login(self.member)

        response = self.client.post(
            self.url,
            self.branding_payload(
                welcome_text="Mensaje del coadministrador."
            ),
        )

        self.assertRedirects(response, self.url)
        self.assertEqual(
            GroupBranding.objects.get(
                group=self.group
            ).welcome_text,
            "Mensaje del coadministrador.",
        )

    def test_regular_member_cannot_edit_branding(self):
        self.client.force_login(self.member)

        get_response = self.client.get(self.url)
        post_response = self.client.post(
            self.url,
            self.branding_payload(),
        )

        self.assertNotContains(
            get_response,
            "Guardar apariencia",
        )
        self.assertRedirects(post_response, self.url)
        self.assertFalse(
            GroupBranding.objects.filter(
                group=self.group
            ).exists()
        )

    def test_plus_group_cannot_activate_branding(self):
        self.group.plan = Group.Plan.PLUS
        self.group.save(update_fields=["plan"])
        self.client.force_login(self.owner)

        get_response = self.client.get(self.url)
        post_response = self.client.post(
            self.url,
            self.branding_payload(),
        )

        self.assertNotContains(
            get_response,
            "Guardar apariencia",
        )
        self.assertRedirects(post_response, self.url)
        self.assertFalse(
            GroupBranding.objects.filter(
                group=self.group
            ).exists()
        )

    def test_expired_club_branding_is_stored_but_hidden(self):
        GroupBranding.objects.create(
            group=self.group,
            primary_color="#E45C72",
            accent_color="#E88A2D",
            welcome_text="Mensaje que no debe aparecer.",
        )
        self.group.plan_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.group.save(update_fields=["plan_expires_at"])
        self.client.force_login(self.owner)
        self.activate_group()

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(
            response,
            "group-branding-active",
        )
        self.assertNotContains(
            response,
            "Mensaje que no debe aparecer.",
        )
        self.assertTrue(
            GroupBranding.objects.filter(
                group=self.group
            ).exists()
        )

    def test_invalid_color_and_oversized_logo_are_rejected(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            self.branding_payload(
                primary_color="javascript:alert(1)",
                logo=self.image_upload(width=1601),
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "primary_color",
            response.context["branding_form"].errors,
        )
        self.assertIn(
            "logo",
            response.context["branding_form"].errors,
        )
        self.assertFalse(
            GroupBranding.objects.filter(
                group=self.group
            ).exists()
        )

    def test_deleting_group_removes_stored_images_after_commit(self):
        branding = GroupBranding(
            group=self.group,
            logo=self.image_upload(),
            hero_image=self.image_upload(
                width=1200,
                height=600,
                filename="company-hero.png",
            ),
        )
        branding.full_clean()
        branding.save()
        logo_path = Path(branding.logo.path)
        hero_path = Path(branding.hero_image.path)
        self.assertTrue(logo_path.exists())
        self.assertTrue(hero_path.exists())

        with self.captureOnCommitCallbacks(execute=True):
            self.group.delete()

        self.assertFalse(logo_path.exists())
        self.assertFalse(hero_path.exists())

    def test_stylesheet_contains_only_validated_branding_values(self):
        GroupBranding.objects.create(
            group=self.group,
            primary_color="#11AA77",
            accent_color="#F2B233",
            background_color="#CDE4F7",
            theme_mode=GroupBranding.ThemeMode.LIGHT,
            brand_intensity=(
                GroupBranding.BrandIntensity.SUBTLE
            ),
        )
        self.client.force_login(self.member)

        response = self.client.get(
            reverse(
                "group_branding_css",
                args=[self.group.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "text/css; charset=utf-8",
        )
        self.assertEqual(
            response["X-Content-Type-Options"],
            "nosniff",
        )
        css = response.content.decode()
        self.assertIn("body.group-branding-active", css)
        self.assertIn("--group-brand-primary:#11AA77", css)
        self.assertIn("--group-brand-text:#17233B", css)
        self.assertIn("--group-brand-wash:0.1", css)

    def test_only_manager_can_request_preview_stylesheet(self):
        self.client.force_login(self.member)
        url = reverse(
            "group_branding_css",
            args=[self.group.id],
        )

        member_response = self.client.get(
            url,
            {
                "preview": "1",
                "primary": "#AABBCC",
            },
        )

        self.assertEqual(member_response.status_code, 404)

        self.client.force_login(self.owner)
        manager_response = self.client.get(
            url,
            {
                "preview": "1",
                "primary": "red;}body{display:none",
                "theme": "unexpected",
            },
        )
        css = manager_response.content.decode()

        self.assertEqual(manager_response.status_code, 200)
        self.assertIn(".group-brand-preview", css)
        self.assertIn("--group-brand-primary:#438CFF", css)
        self.assertIn("--group-brand-text:#17233B", css)
        self.assertNotIn("display:none", css)

    def test_owner_can_preview_before_branding_exists(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "group_branding_css",
                args=[self.group.id],
            ),
            {"preview": "1"},
        )

        self.assertEqual(response.status_code, 200)
        css = response.content.decode()
        self.assertIn("--group-brand-text:#17233B", css)
        self.assertIn("--group-brand-background:#E2E7EE", css)

    def test_owner_can_restore_puntero_default_and_remove_files(self):
        branding = GroupBranding(
            group=self.group,
            logo=self.image_upload(),
            hero_image=self.image_upload(
                width=1200,
                height=600,
                filename="company-hero.png",
            ),
        )
        branding.full_clean()
        branding.save()
        logo_path = Path(branding.logo.path)
        hero_path = Path(branding.hero_image.path)
        self.client.force_login(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url,
                {"form_action": "branding_reset"},
            )

        self.assertRedirects(response, self.url)
        self.assertFalse(
            GroupBranding.objects.filter(group=self.group).exists()
        )
        self.assertFalse(logo_path.exists())
        self.assertFalse(hero_path.exists())

    def test_branding_form_renders_all_controls_and_live_preview(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertContains(response, "data-brand-preview")
        self.assertContains(response, 'name="background_color"')
        self.assertContains(response, 'name="theme_mode"')
        self.assertContains(response, 'name="brand_intensity"')
        self.assertContains(response, 'name="hero_image"')
        self.assertContains(
            response,
            "Restaurar diseño estándar de Puntero",
        )
