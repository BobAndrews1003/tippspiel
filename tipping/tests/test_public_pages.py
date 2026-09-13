from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(LEGAL_PAGES_ENABLED=False)
class PublicPageTests(TestCase):

    def test_public_home_replaces_login_redirect_for_guests(self):
        response = self.client.get(
            reverse("root")
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertTemplateUsed(
            response,
            "tipping/public_home.html",
        )
        self.assertContains(
            response,
            "La emoción del fútbol se comparte mejor.",
        )
        self.assertContains(
            response,
            f'href="{reverse("account_signup")}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("account_login")}"',
        )

    def test_authenticated_root_still_redirects_to_dashboard(self):
        user = get_user_model().objects.create_user(
            username="public-page-user",
            password="safe-public-page-password-2026",
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("root")
        )

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_help_page_is_public_and_links_to_rules(self):
        response = self.client.get(
            reverse("help_page")
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertTemplateUsed(
            response,
            "tipping/help.html",
        )
        self.assertContains(
            response,
            "Preguntas frecuentes",
        )
        self.assertContains(
            response,
            "¿Cómo se calculan los puntos?",
        )
        self.assertContains(
            response,
            f'href="{reverse("rules")}"',
        )

    def test_help_is_linked_when_legal_pages_are_hidden(self):
        response = self.client.get(
            reverse("account_login")
        )

        self.assertContains(
            response,
            f'href="{reverse("help_page")}"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("privacy_policy")}"',
        )

    def test_public_pages_reject_post_requests(self):
        for url_name in ("root", "help_page"):
            with self.subTest(url_name=url_name):
                response = self.client.post(
                    reverse(url_name)
                )

                self.assertEqual(
                    response.status_code,
                    405,
                )
