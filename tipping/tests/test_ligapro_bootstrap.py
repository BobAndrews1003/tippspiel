from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from tipping.models import (
    Match,
    Tournament,
)


@override_settings(
    LIGAPRO_SYNC_TOURNAMENT="LigaPro Ecuador",
)
class LigaProBootstrapTests(TestCase):
    def test_empty_database_is_imported_and_second_run_is_idempotent(self):
        first_output = StringIO()

        call_command(
            "bootstrap_ligapro",
            stdout=first_output,
        )

        tournament = Tournament.objects.get(
            name="LigaPro Ecuador",
        )
        self.assertEqual(
            tournament.matches.count(),
            312,
        )
        self.assertIn(
            "LigaPro-Erstimport erfolgreich",
            first_output.getvalue(),
        )

        second_output = StringIO()
        call_command(
            "bootstrap_ligapro",
            stdout=second_output,
        )

        self.assertEqual(
            tournament.matches.count(),
            312,
        )
        self.assertIn(
            "bereits vollständig",
            second_output.getvalue(),
        )

        first_match = tournament.matches.order_by(
            "id"
        ).first()
        tournament.matches.filter(
            pk=first_match.pk,
        ).update(
            home_team="Unbekannte Testmannschaft",
        )

        with self.assertRaisesMessage(
            CommandError,
            "weicht von den versionierten",
        ):
            call_command("bootstrap_ligapro")

    def test_partial_schedule_stops_without_importing_more_matches(self):
        tournament = Tournament.objects.create(
            name="LigaPro Ecuador",
        )
        Match.objects.create(
            tournament=tournament,
            home_team="Aucas",
            away_team="Macará",
            kickoff=timezone.now(),
            matchday=1,
        )

        with self.assertRaisesMessage(
            CommandError,
            "unvollständig",
        ):
            call_command("bootstrap_ligapro")

        self.assertEqual(
            tournament.matches.count(),
            1,
        )
