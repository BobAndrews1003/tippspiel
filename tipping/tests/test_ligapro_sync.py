from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from tipping.ligapro_sync import (
    LIGAPRO_SOURCE,
    LigaProFeedError,
    LigaProFixture,
    next_ligapro_sync_delay,
    parse_ligapro_payload,
    sync_ligapro_matches,
)
from tipping.models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    Prediction,
    Tournament,
)


def fixture_payload(
    *,
    status="Playing",
    time="15:30:00",
    home_score=1,
    away_score=0,
    home_team="SD Aucas",
    away_team="CSD Macará",
):
    return {
        "result": [
            {
                "fechaSemana": "1",
                "partidos": [
                    {
                        "idPartido": "official-match-1",
                        "estadoComet": status,
                        "fechaPartido": "2026-11-08",
                        "horaPartido": time,
                        "clubLocal": {
                            "razonSocialLocal": home_team,
                            "scoreLocal": home_score,
                        },
                        "clubVisitante": {
                            "razonSocialVisitante": away_team,
                            "scoreVisitante": away_score,
                        },
                    }
                ],
            }
        ]
    }


@override_settings(
    LIGAPRO_SYNC_TOURNAMENT="LigaPro Ecuador",
    LIGAPRO_SYNC_LIVE_SECONDS=120,
    LIGAPRO_SYNC_IDLE_SECONDS=21600,
    LIGAPRO_SYNC_WINDOW_BEFORE_MINUTES=30,
    LIGAPRO_SYNC_WINDOW_AFTER_MINUTES=300,
)
class LigaProSyncTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name="LigaPro Ecuador",
        )
        self.kickoff = timezone.make_aware(
            datetime(
                2026,
                11,
                8,
                23,
                59,
            ),
            timezone.get_current_timezone(),
        )
        self.match = Match.objects.create(
            tournament=self.tournament,
            home_team="Aucas",
            away_team="Macará",
            kickoff=self.kickoff,
            matchday=1,
        )

    def parsed_fixture(self, **payload_kwargs):
        return parse_ligapro_payload(
            fixture_payload(**payload_kwargs),
            minimum_fixtures=1,
            maximum_fixtures=10,
        )[0]

    def test_parser_accepts_scheduled_dash_scores_and_missing_time(self):
        fixture = self.parsed_fixture(
            status="Fixture",
            time=None,
            home_score="-",
            away_score="-",
        )

        self.assertEqual(
            fixture.status,
            Match.SourceStatus.SCHEDULED,
        )
        self.assertIsNone(fixture.kickoff)
        self.assertIsNone(fixture.home_score)
        self.assertEqual(fixture.home_team, "Aucas")
        self.assertEqual(fixture.away_team, "Macará")

    def test_parser_rejects_unknown_team(self):
        with self.assertRaises(LigaProFeedError):
            self.parsed_fixture(
                home_team="Equipo desconocido",
            )

    def test_dry_run_changes_nothing(self):
        result = sync_ligapro_matches(
            apply=False,
            fixtures=[self.parsed_fixture()],
        )

        self.assertEqual(result.matched, 1)
        self.assertEqual(result.linked, 1)
        self.assertEqual(result.live_updates, 1)

        self.match.refresh_from_db()
        self.assertEqual(self.match.external_id, "")
        self.assertIsNone(self.match.live_home_score)
        self.assertEqual(self.match.kickoff, self.kickoff)

    def test_unmatched_fixture_rolls_back_complete_apply(self):
        unmatched_fixture = LigaProFixture(
            external_id="official-unmatched",
            source_round=9,
            match_date=self.kickoff.date(),
            kickoff=None,
            home_team="Barcelona SC",
            away_team="Emelec",
            status=Match.SourceStatus.SCHEDULED,
            home_score=None,
            away_score=None,
        )

        result = sync_ligapro_matches(
            apply=True,
            fixtures=[
                self.parsed_fixture(),
                unmatched_fixture,
            ],
        )

        self.assertEqual(len(result.unmatched), 1)
        self.match.refresh_from_db()
        self.assertEqual(self.match.external_id, "")
        self.assertIsNone(self.match.live_home_score)

    def test_live_score_is_stored_without_final_result(self):
        result = sync_ligapro_matches(
            apply=True,
            fixtures=[self.parsed_fixture()],
        )

        self.match.refresh_from_db()
        self.assertEqual(result.live_updates, 1)
        self.assertEqual(
            self.match.external_source,
            LIGAPRO_SOURCE,
        )
        self.assertEqual(
            self.match.external_id,
            "official-match-1",
        )
        self.assertEqual(
            self.match.source_status,
            Match.SourceStatus.LIVE,
        )
        self.assertEqual(self.match.live_home_score, 1)
        self.assertEqual(self.match.live_away_score, 0)
        self.assertIsNone(self.match.home_score)
        self.assertIsNone(self.match.away_score)
        self.assertEqual(
            timezone.localtime(self.match.kickoff).hour,
            15,
        )

    def test_missing_source_time_preserves_local_kickoff(self):
        scheduled_fixture = self.parsed_fixture(
            status="Fixture",
            time=None,
            home_score="-",
            away_score="-",
        )

        result = sync_ligapro_matches(
            apply=True,
            fixtures=[scheduled_fixture],
        )

        self.match.refresh_from_db()
        self.assertEqual(result.kickoff_updates, 0)
        self.assertEqual(self.match.kickoff, self.kickoff)
        self.assertEqual(
            self.match.source_status,
            Match.SourceStatus.SCHEDULED,
        )

    def test_finished_match_triggers_existing_automatic_evaluation(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="liga-sync-user",
            password="test-password-123",
        )
        group = Group.objects.create(
            tournament=self.tournament,
            name="Liga-Sync-Gruppe",
            owner=user,
        )
        GroupMembership.objects.create(
            group=group,
            user=user,
            is_creator=True,
        )
        prediction = Prediction.objects.create(
            group=group,
            user=user,
            match=self.match,
            pred_home=1,
            pred_away=0,
        )
        finished_fixture = self.parsed_fixture(
            status="Played",
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = sync_ligapro_matches(
                apply=True,
                fixtures=[finished_fixture],
            )

        self.match.refresh_from_db()
        prediction.refresh_from_db()

        self.assertEqual(result.final_updates, 1)
        self.assertEqual(self.match.home_score, 1)
        self.assertEqual(self.match.away_score, 0)
        self.assertIsNone(self.match.live_home_score)
        self.assertEqual(prediction.points, 4)
        self.assertEqual(
            GroupStanding.objects.get(
                group=group,
                user=user,
            ).match_points,
            4,
        )

        second_result = sync_ligapro_matches(
            apply=True,
            fixtures=[finished_fixture],
        )
        self.assertEqual(second_result.changed, 0)

    def test_nearby_unfinished_match_uses_live_interval(self):
        Match.objects.filter(pk=self.match.pk).update(
            kickoff=timezone.now() + timedelta(minutes=10),
        )

        self.assertEqual(
            next_ligapro_sync_delay(),
            120,
        )
