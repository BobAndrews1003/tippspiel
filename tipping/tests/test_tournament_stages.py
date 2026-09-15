from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    Group,
    GroupMembership,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
    TournamentStage,
)
from tipping.standings import rebuild_matchday_scores
from tipping.tournament_stages import (
    build_matchday_metadata,
)


class TournamentStageModelTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name="LigaPro fases",
        )

    def test_new_tournament_receives_ligapro_stages(self):
        stages = list(
            self.tournament.stages.values_list(
                "code",
                "name",
                "sort_order",
                "round_count",
            )
        )

        self.assertEqual(
            stages,
            [
                ("regular", "Fase regular", 1, 30),
                (
                    "hexagonal_final",
                    "Hexagonal final",
                    2,
                    10,
                ),
                (
                    "cuadrangular",
                    "Cuadrangular",
                    3,
                    6,
                ),
                (
                    "hexagonal_descenso",
                    "Hexagonal de descenso",
                    4,
                    10,
                ),
            ],
        )

    def test_stage_must_belong_to_match_tournament(self):
        other_tournament = Tournament.objects.create(
            name="Otra liga",
        )
        other_stage = other_tournament.stages.get(
            code=TournamentStage.Code.HEXAGONAL_FINAL,
        )

        match = Match(
            tournament=self.tournament,
            stage=other_stage,
            stage_round=1,
            matchday=31,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=timezone.now(),
        )

        with self.assertRaises(ValidationError):
            match.save()

    def test_stage_round_cannot_exceed_configured_rounds(self):
        cuadrangular = self.tournament.stages.get(
            code=TournamentStage.Code.CUADRANGULAR,
        )
        match = Match(
            tournament=self.tournament,
            stage=cuadrangular,
            stage_round=7,
            matchday=37,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=timezone.now(),
        )

        with self.assertRaises(ValidationError):
            match.save()

    def test_csv_import_assigns_final_stage_and_round(self):
        with TemporaryDirectory() as directory:
            csv_path = Path(directory) / "finales.csv"
            csv_path.write_text(
                "home_team,away_team,dateEvent,matchday,phase,stage_round\n"
                "Equipo A,Equipo B,2026-11-01,31,Hexagonal final,1\n",
                encoding="utf-8",
            )

            call_command(
                "import_matches",
                str(csv_path),
                tournament=self.tournament.name,
                stdout=StringIO(),
            )

        match = Match.objects.get(
            tournament=self.tournament,
            home_team="Equipo A",
        )
        self.assertEqual(
            match.stage.code,
            TournamentStage.Code.HEXAGONAL_FINAL,
        )
        self.assertEqual(match.matchday, 31)
        self.assertEqual(match.stage_round, 1)


class TournamentStageViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="stage-user",
            password="test-password-123",
        )
        self.tournament = Tournament.objects.create(
            name="LigaPro 2026",
        )
        self.group = Group.objects.create(
            name="Grupo con finales",
            tournament=self.tournament,
            owner=self.user,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.user,
            is_creator=True,
        )
        stages = {
            stage.code: stage
            for stage in self.tournament.stages.all()
        }
        kickoff = timezone.now() + timedelta(days=1)
        stage_codes = (
            TournamentStage.Code.HEXAGONAL_FINAL,
            TournamentStage.Code.CUADRANGULAR,
            TournamentStage.Code.HEXAGONAL_DESCENT,
        )
        self.matches = []

        for index, stage_code in enumerate(stage_codes):
            self.matches.append(
                Match.objects.create(
                    tournament=self.tournament,
                    stage=stages[stage_code],
                    stage_round=1,
                    matchday=31,
                    home_team=f"Local {index}",
                    away_team=f"Visitante {index}",
                    kickoff=kickoff + timedelta(hours=index),
                    home_score=2,
                    away_score=1,
                )
            )

        self.client.force_login(self.user)
        session = self.client.session
        session["active_group_id"] = self.group.id
        session.save()

    def test_final_matchday_has_shared_label_and_named_stages(self):
        metadata = build_matchday_metadata(
            self.tournament,
            [31],
        )[31]

        self.assertEqual(
            metadata.label,
            "Finales · Fecha 1",
        )
        self.assertEqual(
            metadata.stage_names,
            (
                "Hexagonal final",
                "Cuadrangular",
                "Hexagonal de descenso",
            ),
        )

        tip_response = self.client.get(
            reverse("tippen"),
            {"md": 31},
        )
        matchday_response = self.client.get(
            reverse("spieltag"),
            {"md": 31},
        )
        dashboard_response = self.client.get(
            reverse("dashboard"),
        )

        for response in (
            tip_response,
            matchday_response,
            dashboard_response,
        ):
            self.assertContains(
                response,
                "Finales · Fecha 1",
            )

        for stage_name in metadata.stage_names:
            self.assertContains(
                tip_response,
                stage_name,
            )
            self.assertContains(
                matchday_response,
                stage_name,
            )

    def test_all_final_stages_share_one_matchday_score(self):
        for match in self.matches:
            Prediction.objects.create(
                user=self.user,
                group=self.group,
                match=match,
                pred_home=2,
                pred_away=1,
                points=4,
            )

        rebuild_matchday_scores(
            group_id=self.group.id,
            matchday=31,
        )

        score = MatchdayScore.objects.get(
            group=self.group,
            user=self.user,
            matchday=31,
        )
        self.assertEqual(score.points, 12)
