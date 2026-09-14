# tipping/forms.py

from __future__ import annotations

from django import forms

from .models import (
    Group,
    GroupBranding,
    Match,
    Tournament,
    UserProfile,
)



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


class GroupSettingsForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = (
            "name",
            "join_enabled",
        )
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "input",
                    "autocomplete": "off",
                }
            ),
            "join_enabled": forms.CheckboxInput(
                attrs={
                    "class": "group-settings-checkbox",
                }
            ),
        }
        labels = {
            "name": "Nombre del grupo",
            "join_enabled": (
                "Permitir que nuevos participantes se unan"
            ),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        if not name:
            raise forms.ValidationError(
                "El nombre del grupo no puede estar vacío."
            )

        return name


class GroupBrandingForm(forms.ModelForm):
    class Meta:
        model = GroupBranding
        fields = (
            "logo",
            "hero_image",
            "primary_color",
            "accent_color",
            "background_color",
            "theme_mode",
            "brand_intensity",
            "welcome_text",
        )
        widgets = {
            "logo": forms.ClearableFileInput(
                attrs={
                    "accept": "image/jpeg,image/png,image/webp",
                }
            ),
            "hero_image": forms.ClearableFileInput(
                attrs={
                    "accept": "image/jpeg,image/png,image/webp",
                }
            ),
            "primary_color": forms.TextInput(
                attrs={
                    "class": "group-brand-color-input",
                    "type": "color",
                }
            ),
            "accent_color": forms.TextInput(
                attrs={
                    "class": "group-brand-color-input",
                    "type": "color",
                }
            ),
            "background_color": forms.TextInput(
                attrs={
                    "class": "group-brand-color-input",
                    "type": "color",
                }
            ),
            "theme_mode": forms.RadioSelect(
                attrs={"class": "group-brand-choice-list"}
            ),
            "brand_intensity": forms.RadioSelect(
                attrs={"class": "group-brand-choice-list"}
            ),
            "welcome_text": forms.Textarea(
                attrs={
                    "class": "input",
                    "rows": 3,
                    "maxlength": 280,
                    "placeholder": (
                        "p. ej. Bienvenidos al torneo interno 2026."
                    ),
                }
            ),
        }
        labels = {
            "logo": "Logotipo",
            "hero_image": "Imagen de portada",
            "primary_color": "Color principal",
            "accent_color": "Color de acento",
            "background_color": "Tono de fondo",
            "theme_mode": "Modo de visualización",
            "brand_intensity": "Intensidad de la marca",
            "welcome_text": "Mensaje de bienvenida",
        }
        help_texts = {
            "logo": (
                "JPG, PNG o WebP; máximo 2 MB y 1600 × 1600 px."
            ),
            "hero_image": (
                "Opcional. JPG, PNG o WebP; máximo 4 MB y "
                "2400 × 1400 px."
            ),
            "background_color": (
                "Se mezcla con una base segura para mantener el contraste."
            ),
            "welcome_text": "Máximo 280 caracteres.",
        }


class BonusPredictionForm(forms.Form):
    herbstmeister = forms.ChoiceField(label="Campeón de medio año", choices=[])
    meister = forms.ChoiceField(label="Campeón", choices=[])
    trainer_first = forms.ChoiceField(label="Primer cambio de entrenador", choices=[])
    topscorer = forms.ChoiceField(label="Máximo goleador", choices=[])
    relegation1 = forms.ChoiceField(label="Desciende 1", choices=[])
    relegation2 = forms.ChoiceField(label="Desciende 2", choices=[])

    TEAM_FIELDS = ("herbstmeister", "meister", "trainer_first", "topscorer", "relegation1", "relegation2")

    def __init__(self, *args, tournament=None, **kwargs):
        super().__init__(*args, **kwargs)

        team_choices = [("", "Seleccionar…")]

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
            self.add_error(
                "relegation2",
                "El segundo equipo descendido no puede ser igual al primero.",
            )
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


class TipReminderSettingsForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = (
            "tip_reminders_enabled",
        )
    
    
