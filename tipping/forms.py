# tipping/forms.py

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.validators import FileExtensionValidator

from .models import Group, Tournament, Match, BonusPrediction


User = get_user_model()


# ---------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------
class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True, label="E-Mail", widget=forms.EmailInput(attrs={"class": "input"}))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")
        widgets = {
            "username": forms.TextInput(attrs={"class": "input"}),
        }

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Este correo ya esta registrado")
        return email

    def save(self, commit: bool = True):
        user = super().save(commit=False)
        user.email = (self.cleaned_data.get("email") or "").strip().lower()
        if commit:
            user.save()
        return user


# ---------------------------------------------------------------------
# Login: Username ODER E-Mail
# ---------------------------------------------------------------------
class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    """
    Ermöglicht Login mit Username ODER E-Mail.
    Django nennt das Feld intern weiterhin 'username'.
    """

    def clean(self):
        username_or_email = (self.cleaned_data.get("username") or "").strip()
        password = self.cleaned_data.get("password")

        if username_or_email and password:
            if "@" in username_or_email:
                user = User.objects.filter(email__iexact=username_or_email).first()
                if user:
                    # AuthenticationForm erwartet hier weiterhin den Username
                    self.cleaned_data["username"] = user.get_username()

        return super().clean()


# ---------------------------------------------------------------------
# Gruppe erstellen (ModelForm -> hat save())
# ---------------------------------------------------------------------
class GroupCreateForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ("name", "tournament")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "p. ej. Amigos de la U", "class": "input"}),
            "tournament": forms.Select(attrs={"class": "input"}),
        }
        labels = {
            "name": "Nombre del grupo",
            "tournament": "Campeonato",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        

        # Turniere sortiert + nice empty label
        self.fields["tournament"].queryset = Tournament.objects.all().order_by("name")
        self.fields["tournament"].empty_label = "Elegir un campeonato…"

        # kleine UX-Extras
        self.fields["name"].required = True
        self.fields["tournament"].required = True


class BonusPredictionForm(forms.Form):
    herbstmeister = forms.ChoiceField(label="Campeon de medio año", choices=[])
    meister = forms.ChoiceField(label="Campeon", choices=[])
    trainer_first = forms.ChoiceField(label="Primer cambio de entrenador", choices=[])
    topscorer = forms.ChoiceField(label="Maxio goleador", choices=[])
    relegation1 = forms.ChoiceField(label="Desciende 1", choices=[])
    relegation2 = forms.ChoiceField(label="Desciende 2", choices=[])

    TEAM_FIELDS = ("herbstmeister", "meister", "trainer_first", "topscorer", "relegation1", "relegation2")

    def __init__(self, *args, tournament=None, **kwargs):
        super().__init__(*args, **kwargs)

        team_choices = [("", "Bitte wählen…")]

        if tournament is not None:
            qs = (
                Match.objects
                .filter(tournament=tournament)
                .values_list("home_team", "away_team")
            )

            teams = set()
            for home, away in qs:
                if home and home.strip():
                    teams.add(home.strip())
                if away and away.strip():
                    teams.add(away.strip())

            for t in sorted(teams, key=lambda s: s.lower()):
                team_choices.append((t, t))

        print("BONUS choices:", len(team_choices), "example:", team_choices[:5])

        # ✅ Wichtig: choices am Feld UND am Widget setzen (damit <option> gerendert wird)
        for name in self.TEAM_FIELDS:
            field = self.fields[name]
            field.choices = team_choices

            field.widget = forms.Select(attrs={
                "class": "input",
                "style": "width:100%; min-width:320px; padding:10px 12px; border:1px solid #ddd; border-radius:10px; background:#fff; color:#111;"
            })
            field.widget.choices = team_choices  # 🔥 das ist der Fix für leere <select>

    def clean(self):
        cleaned = super().clean()
        r1 = cleaned.get("relegation1")
        r2 = cleaned.get("relegation2")
        if r1 and r2 and r1 == r2:
            self.add_error("relegation2", "Absteiger 2 darf nicht identisch mit Absteiger 1 sein.")
        return cleaned
    
class DeleteAccountForm(forms.Form):
    password = forms.CharField(
        label="Contraseña actual",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "input",
                "autocomplete": "current-password",
                "placeholder": "Introduce tu contraseña",
            }
        ),
    )

    confirmation = forms.CharField(
        label='Escribe "ELIMINAR" para confirmar',
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "autocomplete": "off",
                "placeholder": "ELIMINAR",
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]

        if self.user is None:
            raise forms.ValidationError(
                "No se pudo comprobar la cuenta."
            )

        if not self.user.check_password(password):
            raise forms.ValidationError(
                "La contraseña no es correcta."
            )

        return password

    def clean_confirmation(self):
        confirmation = self.cleaned_data["confirmation"]

        if confirmation.strip().upper() != "ELIMINAR":
            raise forms.ValidationError(
                'Debes escribir exactamente "ELIMINAR".'
            )

        return confirmation
    
    
