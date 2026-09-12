from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class AdultSignupTests(TestCase):
    def setUp(self):
        self.signup_url = reverse(
            "account_signup"
        )
        self.valid_data = {
            "username": "adult-user",
            "email": "adult@example.com",
            "password1": "Safe-release-password-2026",
            "password2": "Safe-release-password-2026",
        }

    def test_signup_displays_required_adult_confirmation(self):
        response = self.client.get(
            self.signup_url
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertIn(
            "is_adult",
            response.context["form"].fields,
        )
        self.assertTrue(
            response.context["form"]
            .fields["is_adult"]
            .required
        )
        self.assertContains(
            response,
            "Confirmo que tengo al menos 18 años.",
        )

    def test_signup_without_adult_confirmation_is_rejected(self):
        response = self.client.post(
            self.signup_url,
            self.valid_data,
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertFalse(
            User.objects.filter(
                username="adult-user",
            ).exists()
        )
        self.assertFormError(
            response.context["form"],
            "is_adult",
            (
                "Debes confirmar que tienes al menos "
                "18 años para registrarte."
            ),
        )

    def test_signup_with_adult_confirmation_succeeds(self):
        response = self.client.post(
            self.signup_url,
            {
                **self.valid_data,
                "is_adult": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )
        self.assertTrue(
            User.objects.filter(
                username="adult-user",
                email="adult@example.com",
            ).exists()
        )
