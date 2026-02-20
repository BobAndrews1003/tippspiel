from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


# --- Helpers ---------------------------------------------------------------

def generate_join_code(length: int = 8) -> str:
    """
    Gut lesbarer, nicht-erratbarer Join-Code.
    Ohne 0/O und 1/I zur Vermeidung von Verwechslungen.
    """
    alphabet = "23456789" + "ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# --- Models ----------------------------------------------------------------

class Tournament(models.Model):
    name = models.CharField(max_length=120)

    # 🗓 Saisonstart (ab diesem Zeitpunkt sind Bonustipps gesperrt)
    season_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Ab diesem Zeitpunkt sind Bonustipps gesperrt."
    )

    # 🏆 Offizielle Ergebnisse für Bonuswertung
    autumn_champion = models.CharField(max_length=120, blank=True)
    champion = models.CharField(max_length=120, blank=True)
    first_coach_sacked = models.CharField(max_length=120, blank=True)
    top_scorer = models.CharField(max_length=120, blank=True)
    relegated_teams = models.TextField(
        blank=True,
        help_text="Kommagetrennte Liste der Absteiger"
    )

    def __str__(self) -> str:
        return self.name


class Group(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="groups")
    name = models.CharField(max_length=120)

    # Wer die Gruppe gegründet hat (optional, aber sehr hilfreich)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_groups",
    )

    # Join-Code eindeutig & indexiert. Default generiert automatisch.
    join_code = models.CharField(
        max_length=12,
        unique=True,
        db_index=True,
        default=generate_join_code,
    )

    def __str__(self) -> str:
        return f"{self.name} ({self.tournament.name})"


class Match(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="matches")
    home_team = models.CharField(max_length=80)
    away_team = models.CharField(max_length=80)
    kickoff = models.DateTimeField()

    matchday = models.IntegerField(null=True, blank=True)  # "Fecha" aus der CSV

    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.home_team} vs {self.away_team}"

    @property
    def has_result(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    @property
    def is_locked(self) -> bool:
        # Tipp-Sperre: ab Anpfiff
        return timezone.now() >= self.kickoff


class GroupMembership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    group = models.ForeignKey("Group", on_delete=models.CASCADE, related_name="memberships")

    is_creator = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "group"], name="unique_user_group_membership")
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.group}"


class Prediction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="predictions")
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="predictions")

    pred_home = models.IntegerField(null=True, blank=True)
    pred_away = models.IntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "group", "match"], name="unique_prediction")
        ]

    def __str__(self) -> str:
        return f"{self.user}: {self.match} ({self.pred_home}:{self.pred_away})"


class BonusPrediction(models.Model):
    BONUS_TYPES = [
        ("herbstmeister", "Herbstmeister"),
        ("meister", "Meister"),
        ("trainer_first", "Erste Trainerentlassung"),
        ("topscorer", "Torschützenkönig"),
        ("relegation1", "Absteiger 1"),
        ("relegation2", "Absteiger 2"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="bonus_predictions")
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="bonus_predictions")

    bonus_type = models.CharField(max_length=50, choices=BONUS_TYPES)
    value = models.CharField(max_length=120)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "group", "bonus_type"],
                name="unique_bonus_prediction_per_group"
            )
        ]

    def __str__(self):
        return f"{self.user} – {self.bonus_type}: {self.value}"


