from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class RulesPageTests(TestCase):

    def test_rules_page_is_public(self):
        response = self.client.get(
            reverse("rules")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTemplateUsed(
            response,
            "tipping/rules.html",
        )

        self.assertContains(
            response,
            "Reglas oficiales de Puntero",
        )

        self.assertContains(
            response,
            "Resultado exacto",
        )

        self.assertContains(
            response,
            "no se muestran resultados ni puntos en vivo",
        )

        self.assertContains(
            response,
            "victorias de fecha sirven como desempate",
        )

    def test_rules_page_is_linked_for_anonymous_users(self):
        response = self.client.get(
            reverse("account_login")
        )

        self.assertContains(
            response,
            f'href="{reverse("rules")}"',
        )

    def test_rules_page_is_linked_for_authenticated_users(self):
        user = get_user_model().objects.create_user(
            username="rules-user",
            password="safe-test-password-123",
        )

        self.client.force_login(user)

        response = self.client.get(
            reverse("rules")
        )

        self.assertContains(
            response,
            "Reglas del juego",
        )

        self.assertContains(
            response,
            f'href="{reverse("join_group")}"',
        )

    def test_rules_page_rejects_post(self):
        response = self.client.post(
            reverse("rules")
        )

        self.assertEqual(
            response.status_code,
            405,
        )
