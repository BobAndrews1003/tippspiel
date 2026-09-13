from django.test import TestCase, override_settings
from django.urls import reverse


LEGAL_URL_NAMES = (
    "privacy_policy",
    "terms_of_use",
    "legal_contact",
)


class DisabledLegalPageTests(TestCase):

    @override_settings(LEGAL_PAGES_ENABLED=False)
    def test_legal_pages_are_hidden_by_default(self):
        for url_name in LEGAL_URL_NAMES:
            with self.subTest(url_name=url_name):
                response = self.client.get(
                    reverse(url_name)
                )

                self.assertEqual(
                    response.status_code,
                    404,
                )

    @override_settings(LEGAL_PAGES_ENABLED=False)
    def test_hidden_pages_are_not_linked(self):
        for url_name in ("rules", "account_login"):
            with self.subTest(url_name=url_name):
                response = self.client.get(
                    reverse(url_name)
                )

                self.assertNotContains(
                    response,
                    f'href="{reverse("privacy_policy")}"',
                )
                self.assertNotContains(
                    response,
                    f'href="{reverse("terms_of_use")}"',
                )
                self.assertNotContains(
                    response,
                    f'href="{reverse("legal_contact")}"',
                )


@override_settings(
    LEGAL_PAGES_ENABLED=True,
    LEGAL_PAGES_HAVE_PLACEHOLDERS=True,
    LEGAL_PAGES_LAST_UPDATED="12 de septiembre de 2026",
    LEGAL_OPERATOR_NAME="[COMPLETAR: OPERADOR DE PRUEBA]",
    LEGAL_OPERATOR_ADDRESS="[COMPLETAR: DIRECCIÓN DE PRUEBA]",
    LEGAL_OPERATOR_PHONE="[COMPLETAR: TELÉFONO DE PRUEBA]",
    LEGAL_CONTACT_EMAIL="[COMPLETAR: CORREO DE PRUEBA]",
    LEGAL_HOSTING_REGION="[COMPLETAR: REGIÓN DE PRUEBA]",
    LEGAL_COMMERCIAL_MODEL="[COMPLETAR: MODELO DE PRUEBA]",
    LEGAL_MATCH_EXCEPTION_RULE="[COMPLETAR: REGLA DE PRUEBA]",
)
class EnabledLegalPageTests(TestCase):

    def test_legal_pages_are_public_and_render_their_templates(self):
        expectations = {
            "privacy_policy": (
                "tipping/legal/privacy_policy.html",
                "Política de protección de datos personales",
            ),
            "terms_of_use": (
                "tipping/legal/terms_of_use.html",
                "Términos de uso",
            ),
            "legal_contact": (
                "tipping/legal/contact.html",
                "Contacto e información legal",
            ),
        }

        for url_name, (template_name, heading) in expectations.items():
            with self.subTest(url_name=url_name):
                response = self.client.get(
                    reverse(url_name)
                )

                self.assertEqual(
                    response.status_code,
                    200,
                )
                self.assertTemplateUsed(
                    response,
                    template_name,
                )
                self.assertContains(
                    response,
                    heading,
                )

    def test_drafts_are_marked_and_excluded_from_indexing(self):
        response = self.client.get(
            reverse("privacy_policy")
        )

        self.assertContains(
            response,
            "Borrador interno · No publicar",
        )
        self.assertContains(
            response,
            '<meta name="robots" content="noindex,nofollow">',
            html=True,
        )
        self.assertContains(
            response,
            "[COMPLETAR: OPERADOR DE PRUEBA]",
        )

    def test_enabled_pages_are_linked_in_navigation_and_footer(self):
        response = self.client.get(
            reverse("privacy_policy")
        )

        for url_name in LEGAL_URL_NAMES:
            with self.subTest(url_name=url_name):
                self.assertContains(
                    response,
                    f'href="{reverse(url_name)}"',
                )

        login_response = self.client.get(
            reverse("account_login")
        )

        self.assertContains(
            login_response,
            f'href="{reverse("privacy_policy")}"',
        )
        self.assertContains(
            login_response,
            f'href="{reverse("terms_of_use")}"',
        )

    def test_legal_pages_reject_post_requests(self):
        for url_name in LEGAL_URL_NAMES:
            with self.subTest(url_name=url_name):
                response = self.client.post(
                    reverse(url_name)
                )

                self.assertEqual(
                    response.status_code,
                    405,
                )

    @override_settings(
        LEGAL_PAGES_HAVE_PLACEHOLDERS=False,
        LEGAL_OPERATOR_NAME="Persona operadora",
    )
    def test_reviewed_content_has_no_draft_marker_or_noindex(self):
        response = self.client.get(
            reverse("privacy_policy")
        )

        self.assertNotContains(
            response,
            "Borrador interno · No publicar",
        )
        self.assertNotContains(
            response,
            "noindex,nofollow",
        )
        self.assertContains(
            response,
            "Persona operadora",
        )
