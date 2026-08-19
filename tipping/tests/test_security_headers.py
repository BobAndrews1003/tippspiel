from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse


class SecurityHeaderTests(TestCase):

    def test_csp_report_only_header_is_present(self):
        response = self.client.get(
            reverse("account_login")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        policy = response.headers.get(
            "Content-Security-Policy-Report-Only",
            "",
        )

        self.assertTrue(
            policy,
            "CSP Report-Only Header fehlt.",
        )

        self.assertIn(
            "default-src 'self'",
            policy,
        )

        self.assertIn(
            "object-src 'none'",
            policy,
        )

        self.assertIn(
            "frame-ancestors 'none'",
            policy,
        )

    def test_rate_limit_template_exists(self):
        template = get_template("429.html")

        self.assertIsNotNone(template)
