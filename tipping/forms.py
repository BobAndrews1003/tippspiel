# tipping/forms.py

from __future__ import annotations

from django import forms
from django.db.models import Q

from .models import (
    Group,
    GroupBranding,
    GroupScoringSettings,
    GroupTournamentSelection,
    Match,
    Tournament,
    UserProfile,
)
from .scoring_config import (
    MAX_SCORING_POINTS,
    SCORING_PRESETS,
    ScoringValues,
    identify_scoring_preset,
)



# ---------------------------------------------------------------------
# Gruppe erstellen (ModelForm -> hat save())
# ---------------------------------------------------------------------
class GroupCreateForm(forms.ModelForm):
    tournaments = forms.ModelMultipleChoiceField(
        queryset=Tournament.objects.none(),
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "competition-checkbox"}
        ),
        label="Competiciones",
        help_text=(
            "Selecciona una o varias competiciones de la misma temporada."
        ),
    )

    class Meta:
        model = Group
        fields = ("name",)
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "p. ej. Amigos de la U", "class": "input"}),
        }
        labels = {
            "name": "Nombre del grupo",
        }

    def __init__(self, *args, **kwargs):
        # Übergangsweise akzeptieren wir weiterhin den früheren
        # POST-Parameter ``tournament``. So bleiben ältere Clients und
        # Tests während der Migration funktionsfähig.
        if args and args[0] is not None:
            data = args[0].copy()

            if (
                not data.getlist("tournaments")
                and data.get("tournament")
            ):
                data.setlist(
                    "tournaments",
                    [data["tournament"]],
                )

            args = (data, *args[1:])

        super().__init__(*args, **kwargs)

        self.fields["tournaments"].queryset = (
            Tournament.objects
            .filter(
                is_selectable=True,
            )
            .filter(
                Q(season__isnull=True)
                | Q(
                    season__is_open_for_groups=True,
                )
            )
            .select_related("season")
            .order_by(
                "-season__year",
                "season__name",
                "name",
                "id",
            )
        )

        self.fields["tournaments"].label_from_instance = (
            lambda tournament: (
                f"{tournament.season.name} · {tournament.name}"
                if tournament.season_id
                else tournament.name
            )
        )

        # kleine UX-Extras
        self.fields["name"].required = True
        self.fields["tournaments"].required = True

    def clean_tournaments(self):
        tournaments = self.cleaned_data["tournaments"]
        season_ids = {
            tournament.season_id
            for tournament in tournaments
        }

        if len(season_ids) > 1:
            raise forms.ValidationError(
                "Todas las competiciones deben pertenecer a la misma temporada."
            )

        return tournaments

    def save(self, commit=True):
        group = super().save(commit=False)
        tournaments = self._ordered_tournaments()
        group.tournament = tournaments[0]

        if commit:
            group.save()
            self.save_tournament_selections(group)

        return group

    def save_tournament_selections(self, group: Group) -> None:
        tournaments = self._ordered_tournaments()

        GroupTournamentSelection.objects.filter(
            group=group,
        ).exclude(
            tournament__in=tournaments,
        ).delete()

        for sort_order, tournament in enumerate(
            tournaments,
            start=1,
        ):
            GroupTournamentSelection.objects.update_or_create(
                group=group,
                tournament=tournament,
                defaults={
                    "sort_order": sort_order,
                },
            )

    def _ordered_tournaments(self) -> list[Tournament]:
        tournaments = list(
            self.cleaned_data["tournaments"]
        )

        return sorted(
            tournaments,
            key=lambda tournament: (
                0 if tournament.code == "ligapro" else 1,
                tournament.name.lower(),
                tournament.id,
            ),
        )


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


class GroupScoringSettingsForm(forms.ModelForm):
    preset = forms.ChoiceField(
        choices=(
            *(
                (code, label)
                for code, (label, _values)
                in SCORING_PRESETS.items()
            ),
            ("custom", "Personalizado"),
        ),
        widget=forms.RadioSelect(
            attrs={"class": "group-scoring-preset-list"}
        ),
        label="Modelo de puntuación",
    )

    class Meta:
        model = GroupScoringSettings
        fields = (
            "exact_points",
            "goal_difference_points",
            "tendency_points",
            "incorrect_points",
        )
        widgets = {
            field_name: forms.NumberInput(
                attrs={
                    "class": "input group-scoring-number",
                    "min": 0,
                    "max": MAX_SCORING_POINTS,
                    "inputmode": "numeric",
                }
            )
            for field_name in (
                "exact_points",
                "goal_difference_points",
                "tendency_points",
                "incorrect_points",
            )
        }
        labels = {
            "exact_points": "Resultado exacto",
            "goal_difference_points": "Diferencia correcta",
            "tendency_points": "Tendencia correcta",
            "incorrect_points": "Pronóstico incorrecto",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.is_bound and self.instance.pk:
            values = ScoringValues(
                exact_points=self.instance.exact_points,
                goal_difference_points=(
                    self.instance.goal_difference_points
                ),
                tendency_points=self.instance.tendency_points,
                incorrect_points=self.instance.incorrect_points,
            )
            self.initial["preset"] = identify_scoring_preset(
                values
            )

    def clean(self):
        cleaned = super().clean()

        if self.instance.is_locked:
            raise forms.ValidationError(
                "El sistema de puntuación ya está bloqueado."
            )

        preset = cleaned.get("preset")

        if preset in SCORING_PRESETS:
            _label, values = SCORING_PRESETS[preset]
            cleaned.update(
                {
                    "exact_points": values.exact_points,
                    "goal_difference_points": (
                        values.goal_difference_points
                    ),
                    "tendency_points": values.tendency_points,
                    "incorrect_points": values.incorrect_points,
                }
            )

            for field_name in self.Meta.fields:
                setattr(
                    self.instance,
                    field_name,
                    cleaned[field_name],
                )

        return cleaned


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
    
    
