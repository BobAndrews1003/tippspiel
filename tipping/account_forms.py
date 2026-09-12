from django import forms

from allauth.account.forms import SignupForm


class AdultSignupForm(SignupForm):
    """Registrierung nur nach ausdrücklicher 18+-Bestätigung."""

    is_adult = forms.BooleanField(
        required=True,
        label=(
            "Confirmo que tengo al menos 18 años."
        ),
        error_messages={
            "required": (
                "Debes confirmar que tienes al menos "
                "18 años para registrarte."
            ),
        },
    )

    field_order = (
        "username",
        "email",
        "password1",
        "password2",
        "is_adult",
    )
