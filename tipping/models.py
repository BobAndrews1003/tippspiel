from __future__ import annotations

import secrets
import warnings
from pathlib import Path
from uuid import uuid4


from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MinLengthValidator,
)
from django.db import models
from django.utils import timezone


# ============================================================
# Zentrale Grenzwerte
# ============================================================

MAX_GOALS = 30
MAX_MATCHDAY = 200

JOIN_CODE_LENGTH = 16

MAX_AVATAR_FILE_SIZE = 3 * 1024 * 1024
MAX_AVATAR_WIDTH = 3000
MAX_AVATAR_HEIGHT = 3000

ALLOWED_AVATAR_EXTENSIONS = (
    "jpg",
    "jpeg",
    "png",
    "webp",
)

ALLOWED_AVATAR_FORMATS = {
    "JPEG": {
        ".jpg",
        ".jpeg",
    },
    "PNG": {
        ".png",
    },
    "WEBP": {
        ".webp",
    },
}


BONUS_TYPE_CHOICES = (
    (
        "herbstmeister",
        "Herbstmeister",
    ),
    (
        "meister",
        "Meister",
    ),
    (
        "trainer_first",
        "Erste Trainerentlassung",
    ),
    (
        "topscorer",
        "Torschützenkönig",
    ),
    (
        "relegation1",
        "Absteiger 1",
    ),
    (
        "relegation2",
        "Absteiger 2",
    ),
)

BONUS_TYPE_VALUES = tuple(
    value
    for value, label in BONUS_TYPE_CHOICES
)


# ============================================================
# Avatar-Validierung
# ============================================================

def avatar_upload_path(
    instance,
    filename: str,
) -> str:
    """
    Nur für die Kompatibilität mit der historischen Migration
    0009_userprofile.py vorhanden.

    Die Anwendung bietet keinen Avatar-Upload mehr an.
    """

    user_id = getattr(
        instance,
        "user_id",
        "unknown",
    )

    return (
        f"avatars/user_{user_id}/{filename}"
    )
    
    # Nicht entfernen:
# Wird von der historischen Migration
# 0010_alter_bonusprediction_tournament_and_more.py importiert.
def validate_avatar_file(value) -> None:
    """
    Nur zur Kompatibilität mit historischen Migrationen.

    Im aktuellen UserProfile-Modell existiert kein Avatarfeld mehr.
    Daher findet über diese Funktion kein Datei-Upload statt.
    """

    return None

# ============================================================
# Zugangscodes
# ============================================================

def generate_join_code(
    length: int = JOIN_CODE_LENGTH,
) -> str:
    """
    Erzeugt einen kryptografisch zufälligen,
    gut lesbaren Gruppencode.

    0/O und 1/I werden ausgelassen, um
    Verwechslungen zu vermeiden.
    """
    alphabet = (
        "23456789"
        "ABCDEFGHJKLMNPQRSTUVWXYZ"
    )

    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


# ============================================================
# UserProfile
# ============================================================

class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tip_profile",
    )



    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self) -> str:
        return f"Perfil de {self.user}"


# ============================================================
# Tournament
# ============================================================

class Tournament(models.Model):
    name = models.CharField(
        max_length=120,
    )

    # Ab diesem Zeitpunkt sind Bonustipps gesperrt.
    season_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Ab diesem Zeitpunkt sind "
            "Bonustipps gesperrt."
        ),
    )

    # Offizielle Ergebnisse für die Bonuswertung.
    autumn_champion = models.CharField(
        max_length=120,
        blank=True,
    )

    champion = models.CharField(
        max_length=120,
        blank=True,
    )

    first_coach_sacked = models.CharField(
        max_length=120,
        blank=True,
    )

    top_scorer = models.CharField(
        max_length=120,
        blank=True,
    )

    relegated_teams = models.TextField(
        blank=True,
        help_text=(
            "Kommagetrennte Liste der Absteiger."
        ),
    )

    def save(
        self,
        *args,
        **kwargs,
    ):
        self.name = self.name.strip()

        return super().save(
            *args,
            **kwargs,
        )

    def __str__(self) -> str:
        return self.name


# ============================================================
# Group
# ============================================================

class Group(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="groups",
    )

    name = models.CharField(
        max_length=120,
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_groups",
    )

    join_code = models.CharField(
        max_length=24,
        unique=True,
        default=generate_join_code,
        validators=[
            MinLengthValidator(12),
        ],
    )

    def save(
        self,
        *args,
        **kwargs,
    ):
        self.name = self.name.strip()

        self.join_code = (
            self.join_code
            .strip()
            .upper()
        )

        return super().save(
            *args,
            **kwargs,
        )

    def rotate_join_code(
        self,
        *,
        save: bool = True,
    ) -> str:
        """
        Erzeugt einen neuen Zugangscode.

        Alte Einladungslinks beziehungsweise
        alte Codes werden dadurch ungültig.
        """
        self.join_code = generate_join_code()

        if save:
            self.save(
                update_fields=[
                    "join_code",
                ],
            )

        return self.join_code

    def __str__(self) -> str:
        return (
            f"{self.name} "
            f"({self.tournament.name})"
        )


# ============================================================
# Match
# ============================================================

class Match(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="matches",
    )

    home_team = models.CharField(
        max_length=80,
    )

    away_team = models.CharField(
        max_length=80,
    )

    kickoff = models.DateTimeField()

    # Spieltag beziehungsweise "Fecha" aus der CSV.
    matchday = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    home_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    away_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            # Spieltag muss entweder leer oder positiv sein.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        matchday__isnull=True,
                    )
                    | models.Q(
                        matchday__gte=1,
                        matchday__lte=MAX_MATCHDAY,
                    )
                ),
                name="match_md_positive_or_null",
            ),

            # Ergebniswerte dürfen nur zwischen
            # 0 und 30 liegen.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        home_score__isnull=True,
                    )
                    | models.Q(
                        home_score__gte=0,
                        home_score__lte=MAX_GOALS,
                    )
                ),
                name="match_home_score_0_30",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        away_score__isnull=True,
                    )
                    | models.Q(
                        away_score__gte=0,
                        away_score__lte=MAX_GOALS,
                    )
                ),
                name="match_away_score_0_30",
            ),

            # Es darf nicht nur ein Teil des
            # Ergebnisses gespeichert werden.
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(
                            home_score__isnull=True,
                        )
                        & models.Q(
                            away_score__isnull=True,
                        )
                    )
                    |
                    (
                        models.Q(
                            home_score__isnull=False,
                        )
                        & models.Q(
                            away_score__isnull=False,
                        )
                    )
                ),
                name="match_result_both_or_none",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "tournament",
                    "matchday",
                ],
                name="match_tournament_md_idx",
            ),

            models.Index(
                fields=[
                    "tournament",
                    "kickoff",
                ],
                name="match_tournament_ko_idx",
            ),
        ]

    def save(
        self,
        *args,
        **kwargs,
    ):
        self.home_team = (
            self.home_team.strip()
        )

        self.away_team = (
            self.away_team.strip()
        )

        return super().save(
            *args,
            **kwargs,
        )

    def __str__(self) -> str:
        return (
            f"{self.home_team} "
            f"vs {self.away_team}"
        )

    @property
    def has_result(self) -> bool:
        return (
            self.home_score is not None
            and self.away_score is not None
        )

    @property
    def is_locked(self) -> bool:
        return (
            self.has_result
            or timezone.now() >= self.kickoff
        )


# ============================================================
# GroupMembership
# ============================================================

class GroupMembership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="group_memberships",
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="memberships",
    )

    is_creator = models.BooleanField(
        default=False,
    )

    joined_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "group",
                ],
                name="unique_user_group_membership",
            ),

            # Höchstens eine Mitgliedschaft darf
            # als Ersteller markiert sein.
            models.UniqueConstraint(
                fields=[
                    "group",
                ],
                condition=models.Q(
                    is_creator=True,
                ),
                name="one_creator_per_group",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "group",
                    "user",
                ],
                name="membership_group_user_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()

        if (
            self.is_creator
            and self.group_id
            and self.user_id
            and self.group.owner_id
            != self.user_id
        ):
            raise ValidationError(
                {
                    "is_creator": (
                        "Solo el propietario del "
                        "grupo puede estar marcado "
                        "como creador."
                    ),
                }
            )

    def save(
        self,
        *args,
        **kwargs,
    ):
        # Django ruft clean() bei save() normalerweise
        # nicht automatisch auf.
        self.clean()

        return super().save(
            *args,
            **kwargs,
        )

    def __str__(self) -> str:
        return (
            f"{self.user} -> {self.group}"
        )


# ============================================================
# Prediction
# ============================================================

class Prediction(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="predictions",
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="predictions",
    )

    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name="predictions",
    )

    pred_home = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    pred_away = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    # null = noch nicht ausgewertet
    # 0–4 = bereits ausgewerteter Tipp
    points = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Berechnete Punkte für diesen Tipp."
        ),
    )

    scored_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "group",
                    "match",
                ],
                name="unique_prediction",
            ),

            # Ein Tipp besteht entweder aus zwei Werten
            # oder aus gar keinem Wert.
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(
                            pred_home__isnull=True,
                        )
                        & models.Q(
                            pred_away__isnull=True,
                        )
                    )
                    |
                    (
                        models.Q(
                            pred_home__isnull=False,
                        )
                        & models.Q(
                            pred_away__isnull=False,
                        )
                    )
                ),
                name="prediction_scores_both_or_none",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        pred_home__isnull=True,
                    )
                    | models.Q(
                        pred_home__gte=0,
                        pred_home__lte=MAX_GOALS,
                    )
                ),
                name="prediction_home_0_30",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        pred_away__isnull=True,
                    )
                    | models.Q(
                        pred_away__gte=0,
                        pred_away__lte=MAX_GOALS,
                    )
                ),
                name="prediction_away_0_30",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        points__isnull=True,
                    )
                    | models.Q(
                        points__gte=0,
                        points__lte=4,
                    )
                ),
                name="prediction_points_0_4",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "group",
                    "match",
                ],
                name="prediction_group_match_idx",
            ),

            models.Index(
                fields=[
                    "group",
                    "user",
                ],
                name="prediction_group_user_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()

        errors = {}

        # Ein Tipp darf nur ein Spiel aus dem
        # Turnier der ausgewählten Gruppe betreffen.
        if (
            self.group_id
            and self.match_id
            and self.group.tournament_id
            != self.match.tournament_id
        ):
            errors["match"] = (
                "El partido no pertenece al "
                "torneo de este grupo."
            )

        # Nur tatsächliche Gruppenmitglieder dürfen
        # Tipps für die Gruppe besitzen.
        if (
            self.user_id
            and self.group_id
            and not GroupMembership.objects.filter(
                user_id=self.user_id,
                group_id=self.group_id,
            ).exists()
        ):
            errors["group"] = (
                "El usuario no pertenece "
                "a este grupo."
            )

        if errors:
            raise ValidationError(errors)

    def save(
        self,
        *args,
        **kwargs,
    ):
        # Erzwingt die gruppenübergreifenden
        # Konsistenzprüfungen auch bei update_or_create().
        self.clean()

        return super().save(
            *args,
            **kwargs,
        )

    def __str__(self) -> str:
        return (
            f"{self.user}: {self.match} "
            f"({self.pred_home}:{self.pred_away})"
        )


# ============================================================
# BonusPrediction
# ============================================================

class BonusPrediction(models.Model):
    BONUS_TYPES = BONUS_TYPE_CHOICES

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bonus_predictions",
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="bonus_predictions",
    )

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="bonus_predictions",
        editable=False,
    )

    bonus_type = models.CharField(
        max_length=50,
        choices=BONUS_TYPE_CHOICES,
    )

    value = models.CharField(
        max_length=120,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "group",
                    "bonus_type",
                ],
                name=(
                    "unique_bonus_prediction_per_group"
                ),
            ),

            # Verhindert unbekannte Bonusarten auch
            # bei direkter Datenbankmanipulation.
            models.CheckConstraint(
                condition=models.Q(
                    bonus_type__in=BONUS_TYPE_VALUES,
                ),
                name="bonus_type_is_valid",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "group",
                    "tournament",
                    "user",
                ],
                name="bonus_group_tourn_user_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()

        errors = {}

        if (
            self.group_id
            and self.tournament_id
            and self.group.tournament_id
            != self.tournament_id
        ):
            errors["tournament"] = (
                "El torneo debe coincidir con "
                "el torneo del grupo."
            )

        if (
            self.user_id
            and self.group_id
            and not GroupMembership.objects.filter(
                user_id=self.user_id,
                group_id=self.group_id,
            ).exists()
        ):
            errors["group"] = (
                "El usuario no pertenece "
                "a este grupo."
            )

        if not self.value.strip():
            errors["value"] = (
                "La respuesta no puede estar vacía."
            )

        if errors:
            raise ValidationError(errors)

    def save(
        self,
        *args,
        **kwargs,
    ):
        # Das Turnier wird immer aus der Gruppe
        # übernommen. Dadurch können keine
        # widersprüchlichen Kombinationen entstehen.
        if self.group_id:
            self.tournament_id = (
                self.group.tournament_id
            )

        self.value = self.value.strip()

        self.clean()

        return super().save(
            *args,
            **kwargs,
        )

    def __str__(self) -> str:
        return (
            f"{self.user} – "
            f"{self.bonus_type}: "
            f"{self.value}"
        )
        
        
class MatchdayScore(models.Model):
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="matchday_scores",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tip_matchday_scores",
    )

    matchday = models.PositiveSmallIntegerField()

    points = models.PositiveIntegerField(
        default=0,
    )

    exact_predictions = models.PositiveIntegerField(
        default=0,
    )

    cumulative_points = models.PositiveIntegerField(
        default=0,
    )

    rank = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    rank_change = models.SmallIntegerField(
        null=True,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "group",
                    "user",
                    "matchday",
                ],
                name="uniq_group_user_matchday",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "group",
                    "matchday",
                    "rank",
                ],
                name="score_group_md_rank_idx",
            ),
            models.Index(
                fields=[
                    "group",
                    "user",
                    "matchday",
                ],
                name="score_group_user_md_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.group_id} · "
            f"{self.user_id} · "
            f"Spieltag {self.matchday}"
        )


class GroupStanding(models.Model):
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="standings",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tip_group_standings",
    )

    match_points = models.PositiveIntegerField(
        default=0,
    )

    bonus_points = models.PositiveIntegerField(
        default=0,
    )

    total_points = models.PositiveIntegerField(
        default=0,
    )

    exact_predictions = models.PositiveIntegerField(
        default=0,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "group",
                    "user",
                ],
                name="uniq_group_user_standing",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "group",
                    "-total_points",
                    "user",
                ],
                name="standing_group_total_idx",
            ),

            models.Index(
                fields=[
                    "group",
                    "-match_points",
                    "user",
                ],
                name="standing_group_match_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.group_id} · "
            f"{self.user_id} · "
            f"{self.total_points} Punkte"
        )